"""
记忆服务层
处理记忆和知识图谱相关的业务逻辑
"""

import time
from typing import Dict, Any, List, Optional
from loguru import logger
from fastapi.concurrency import run_in_threadpool

from ..models.requests import (
    EnhancePromptRequest, UpdateMemoryRequest, ProcessConversationRequest,
    SyncConversationRequest, NodeUpdateRequest, EdgeCreateRequest
)
from ..models.responses import (
    EnhancePromptResponse, UpdateMemoryResponse, ProcessConversationResponse,
    SyncConversationResponse, NodeOperationResponse, EdgeOperationResponse
)
from ...core.game_engine import GameEngine
from ...core.delayed_update import DelayedUpdateManager
from ...core.conflict_resolver import ConflictResolver
from ...utils.exceptions import SessionError, GraphError, ErrorCode
from ...utils.security import get_security_manager


class MemoryService:
    """记忆服务"""

    def __init__(self):
        self.security_manager = get_security_manager()
        # 这些将从会话服务中获取
        self._sessions: Dict[str, GameEngine] = {}
        self._sliding_window_managers: Dict[str, DelayedUpdateManager] = {}
        self._conflict_resolvers: Dict[str, ConflictResolver] = {}

    def set_sessions(self, sessions: Dict[str, GameEngine]):
        """设置会话引用"""
        self._sessions = sessions

    def set_sliding_window_managers(self, managers: Dict[str, DelayedUpdateManager]):
        """设置滑动窗口管理器引用"""
        self._sliding_window_managers = managers

    def set_conflict_resolvers(self, resolvers: Dict[str, ConflictResolver]):
        """设置冲突解决器引用"""
        self._conflict_resolvers = resolvers

    async def enhance_prompt(self, req: EnhancePromptRequest) -> EnhancePromptResponse:
        """增强提示词"""
        if req.session_id not in self._sessions:
            raise SessionError(
                f"Session {req.session_id} not found",
                session_id=req.session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        try:
            engine = self._sessions[req.session_id]

            # 输入清理
            user_input = self.security_manager.sanitize_input(req.user_input)

            # 1. 感知用户输入中的实体
            perception_result = engine.perception.analyze(user_input, engine.memory.knowledge_graph)
            entities = perception_result.get("entities", [])
            intent = perception_result.get("intent", "unknown")

            # 2. 从知识图谱中检索相关上下文
            recent_turns = min(req.max_context_length // 200, 5) if req.max_context_length else 3
            context = engine.memory.retrieve_context_for_prompt(entities, recent_turns=recent_turns)

            # 3. 如果上下文过长，进行智能截断
            if len(context) > req.max_context_length:
                context = context[:req.max_context_length - 100] + "\n[...context truncated...]"

            logger.info(f"Enhanced prompt for session {req.session_id[:8]}... | Entities: {entities} | Intent: {intent}")

            return EnhancePromptResponse(
                enhanced_context=context,
                entities_found=entities,
                context_stats={
                    "entities_count": len(entities),
                    "context_length": len(context),
                    "intent": intent,
                    "graph_nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                    "graph_edges": len(engine.memory.knowledge_graph.graph.edges())
                }
            )

        except Exception as e:
            logger.error(f"Error during prompt enhancement: {e}")
            raise SessionError(
                f"Failed to enhance prompt: {e}",
                session_id=req.session_id,
                error_code=ErrorCode.SESSION_EXPIRED
            )

    async def update_memory(self, req: UpdateMemoryRequest) -> UpdateMemoryResponse:
        """更新记忆"""
        if req.session_id not in self._sessions:
            raise SessionError(
                f"Session {req.session_id} not found",
                session_id=req.session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        try:
            engine = self._sessions[req.session_id]

            # 输入清理
            llm_response = self.security_manager.sanitize_input(req.llm_response)
            user_input = self.security_manager.sanitize_input(req.user_input)

            # 1. 调用GameEngine方法从LLM回复中提取并应用状态更新
            update_results = await run_in_threadpool(
                engine.extract_updates_from_response, llm_response, user_input
            )

            # 2. 将当前的用户输入和LLM回复存入对话历史
            engine.memory.add_conversation(user_input, llm_response)

            # 3. 保存所有记忆更新
            engine.memory.save_all_memory()

            logger.info(f"Memory updated for session {req.session_id[:8]}... | "
                       f"Nodes: {update_results.get('nodes_updated', 0)}, "
                       f"Edges: {update_results.get('edges_added', 0)}")

            return UpdateMemoryResponse(
                message="Memory updated successfully.",
                nodes_updated=update_results.get("nodes_updated", 0),
                edges_added=update_results.get("edges_added", 0),
                processing_stats={
                    "timestamp": req.timestamp,
                    "chat_id": req.chat_id,
                    "llm_response_length": len(llm_response),
                    "user_input_length": len(user_input),
                    "total_graph_nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                    "total_graph_edges": len(engine.memory.knowledge_graph.graph.edges())
                }
            )

        except Exception as e:
            logger.error(f"Error during memory update: {e}")
            raise SessionError(
                f"Failed to update memory: {e}",
                session_id=req.session_id,
                error_code=ErrorCode.SESSION_EXPIRED
            )

    async def process_conversation(self, req: ProcessConversationRequest) -> ProcessConversationResponse:
        """使用滑动窗口系统处理新的对话轮次"""
        if req.session_id not in self._sessions:
            raise SessionError(
                f"Session {req.session_id} not found",
                session_id=req.session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        try:
            # 输入清理
            user_input = self.security_manager.sanitize_input(req.user_input)
            llm_response = self.security_manager.sanitize_input(req.llm_response)

            # 预览输入
            logger.info(f"[SW] Inbound turn | session={req.session_id[:8]}... | "
                       f"user_input_len={len(user_input)} | llm_response_len={len(llm_response)}")

            # 获取或创建滑动窗口管理器
            if req.session_id not in self._sliding_window_managers:
                # 回退到原始处理方式
                logger.warning(f"Sliding window system not initialized for session {req.session_id}, using fallback")
                engine = self._sessions[req.session_id]
                update_results = await run_in_threadpool(
                    engine.extract_updates_from_response, llm_response, user_input
                )
                engine.memory.add_conversation(user_input, llm_response)
                engine.memory.save_all_memory()

                return ProcessConversationResponse(
                    message="Processed using fallback method",
                    turn_sequence=1,
                    turn_processed=True,
                    target_processed=True,
                    window_size=1,
                    nodes_updated=update_results.get("nodes_updated", 0),
                    edges_added=update_results.get("edges_added", 0)
                )

            # 使用滑动窗口系统处理对话
            sliding_manager = self._sliding_window_managers[req.session_id]
            result = await run_in_threadpool(
                sliding_manager.process_new_conversation, user_input, llm_response
            )

            logger.info(f"Sliding window processed conversation for session {req.session_id[:8]}... | "
                       f"Turn: {result['new_turn_sequence']}, Target processed: {result['target_processed']}")

            return ProcessConversationResponse(
                message="Conversation processed successfully with sliding window",
                turn_sequence=result['new_turn_sequence'],
                turn_processed=True,
                target_processed=result['target_processed'],
                window_size=result['window_info']['current_turns'],
                nodes_updated=result.get('grag_updates', {}).get('nodes_updated', 0),
                edges_added=result.get('grag_updates', {}).get('edges_added', 0),
                processing_stats={
                    "timestamp": req.timestamp,
                    "chat_id": req.chat_id,
                    "tavern_message_id": req.tavern_message_id,
                    "llm_response_length": len(llm_response),
                    "user_input_length": len(user_input),
                    "new_turn_id": result['new_turn_id'],
                    "window_info": result['window_info']
                }
            )

        except Exception as e:
            logger.error(f"Error during sliding window conversation processing: {e}")
            raise SessionError(
                f"Failed to process conversation: {e}",
                session_id=req.session_id,
                error_code=ErrorCode.SESSION_EXPIRED
            )

    async def sync_conversation(self, req: SyncConversationRequest) -> SyncConversationResponse:
        """同步SillyTavern对话历史，解决冲突"""
        if req.session_id not in self._sessions:
            raise SessionError(
                f"Session {req.session_id} not found",
                session_id=req.session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        try:
            # 获取冲突解决器
            if req.session_id not in self._conflict_resolvers:
                logger.warning(f"Conflict resolver not available for session {req.session_id}")
                return SyncConversationResponse(
                    message="Conflict resolution not available - sliding window system not initialized",
                    conflicts_detected=0,
                    conflicts_resolved=0,
                    window_synced=False
                )

            conflict_resolver = self._conflict_resolvers[req.session_id]

            # 输入清理和验证
            cleaned_history = []
            for turn in req.tavern_history:
                if isinstance(turn, dict):
                    cleaned_turn = {}
                    for key, value in turn.items():
                        if isinstance(value, str):
                            cleaned_turn[key] = self.security_manager.sanitize_input(value)
                        else:
                            cleaned_turn[key] = value
                    cleaned_history.append(cleaned_turn)

            # 同步对话状态
            hist_len = len(cleaned_history)
            logger.info(f"[SYNC] Starting conversation sync | "
                       f"session={req.session_id[:8]}... | history_len={hist_len}")

            sync_result = await run_in_threadpool(
                conflict_resolver.sync_conversation_state, cleaned_history
            )

            logger.info(f"[SYNC] Conversation sync result | "
                       f"session={req.session_id[:8]}... | "
                       f"conflicts_detected={sync_result.get('conflicts_detected')} | "
                       f"conflicts_resolved={sync_result.get('conflicts_resolved')}")

            return SyncConversationResponse(
                message="Conversation state synchronized successfully",
                conflicts_detected=sync_result['conflicts_detected'],
                conflicts_resolved=sync_result['conflicts_resolved'],
                window_synced=sync_result.get('window_synced', True)
            )

        except Exception as e:
            logger.error(f"Error during conversation sync: {e}")
            raise SessionError(
                f"Failed to sync conversation: {e}",
                session_id=req.session_id,
                error_code=ErrorCode.SESSION_EXPIRED
            )

    async def update_node(self, session_id: str, old_node_name: str, node_data: NodeUpdateRequest) -> NodeOperationResponse:
        """更新节点"""
        if session_id not in self._sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        try:
            engine = self._sessions[session_id]

            # URL解码节点名称
            import urllib.parse
            old_node_name = urllib.parse.unquote(old_node_name)

            # 输入清理
            new_node_name = self.security_manager.sanitize_input(node_data.name)
            description = self.security_manager.sanitize_input(node_data.description)

            logger.info(f"💾 [API] 更新节点: {old_node_name} -> {new_node_name} (类型: {node_data.type})")

            # 如果节点名称变了，使用重命名功能
            if old_node_name != new_node_name:
                logger.info(f"🔄 [API] 检测到节点重命名: {old_node_name} -> {new_node_name}")

                if engine.memory.knowledge_graph.graph.has_node(old_node_name):
                    success = engine.memory.rename_node(old_node_name, new_node_name)
                    if not success:
                        raise GraphError(
                            f"Failed to rename node from {old_node_name} to {new_node_name}",
                            node_id=old_node_name,
                            error_code=ErrorCode.GRAPH_OPERATION_FAILED
                        )
                else:
                    logger.warning(f"[WARN] [API] 旧节点不存在: {old_node_name}")

            # 更新节点属性
            attributes = node_data.attributes.copy() if node_data.attributes else {}
            attributes.update({
                "name": new_node_name,
                "description": description
            })

            engine.memory.add_or_update_node(new_node_name, node_data.type, **attributes)

            # 保存更改
            engine.memory._data_changed = True
            engine.memory.save_all_memory()

            # 获取统计信息
            nodes_count = len(engine.memory.knowledge_graph.graph.nodes())
            edges_count = len(engine.memory.knowledge_graph.graph.edges())

            logger.info(f"[OK] [API] 节点更新成功: {new_node_name}")

            return NodeOperationResponse(
                message="Node updated successfully",
                node_name=new_node_name,
                node_type=node_data.type,
                total_nodes=nodes_count,
                total_edges=edges_count
            )

        except Exception as e:
            logger.error(f"❌ [API] 更新节点失败: {e}")
            raise GraphError(
                f"Failed to update node: {e}",
                node_id=old_node_name,
                error_code=ErrorCode.GRAPH_OPERATION_FAILED
            )

    async def delete_node(self, session_id: str, node_name: str) -> NodeOperationResponse:
        """删除节点"""
        if session_id not in self._sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        try:
            engine = self._sessions[session_id]

            # URL解码节点名称
            import urllib.parse
            node_name = urllib.parse.unquote(node_name)
            logger.info(f"🗑️ [API] 删除节点: {node_name}")

            # 检查节点是否存在
            if not engine.memory.knowledge_graph.graph.has_node(node_name):
                raise GraphError(
                    f"Node '{node_name}' not found",
                    node_id=node_name,
                    error_code=ErrorCode.NODE_NOT_FOUND
                )

            # 删除节点
            success = engine.memory.delete_node(node_name)
            if not success:
                raise GraphError(
                    f"Failed to delete node: {node_name}",
                    node_id=node_name,
                    error_code=ErrorCode.GRAPH_OPERATION_FAILED
                )

            # 保存更改
            engine.memory._data_changed = True
            engine.memory.save_all_memory()

            # 获取删除后的统计信息
            nodes_count = len(engine.memory.knowledge_graph.graph.nodes())
            edges_count = len(engine.memory.knowledge_graph.graph.edges())

            logger.info(f"[OK] [API] 节点删除成功: {node_name}")

            return NodeOperationResponse(
                message="Node deleted successfully",
                node_name=node_name,
                node_type="deleted",
                total_nodes=nodes_count,
                total_edges=edges_count
            )

        except Exception as e:
            logger.error(f"❌ [API] 删除节点失败: {e}")
            raise GraphError(
                f"Failed to delete node: {e}",
                node_id=node_name,
                error_code=ErrorCode.GRAPH_OPERATION_FAILED
            )

    async def create_edge(self, session_id: str, edge_data: EdgeCreateRequest) -> EdgeOperationResponse:
        """创建关系"""
        if session_id not in self._sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        try:
            engine = self._sessions[session_id]

            # 输入清理
            source = self.security_manager.sanitize_input(edge_data.source)
            target = self.security_manager.sanitize_input(edge_data.target)
            relationship = self.security_manager.sanitize_input(edge_data.relationship)
            description = self.security_manager.sanitize_input(edge_data.description)

            logger.info(f"[LINK] [API] 创建关系: {source} --{relationship}--> {target}")

            # 检查源节点和目标节点是否存在
            if not engine.memory.knowledge_graph.graph.has_node(source):
                raise GraphError(
                    f"Source node '{source}' not found",
                    node_id=source,
                    error_code=ErrorCode.NODE_NOT_FOUND
                )

            if not engine.memory.knowledge_graph.graph.has_node(target):
                raise GraphError(
                    f"Target node '{target}' not found",
                    node_id=target,
                    error_code=ErrorCode.NODE_NOT_FOUND
                )

            # 创建关系
            attributes = edge_data.attributes.copy() if edge_data.attributes else {}
            if description:
                attributes["description"] = description

            engine.memory.add_edge(source, target, relationship, **attributes)

            # 保存更改
            engine.memory._data_changed = True
            engine.memory.save_all_memory()

            # 获取统计信息
            edges_count = len(engine.memory.knowledge_graph.graph.edges())

            logger.info(f"[OK] [API] 关系创建成功: {source} --{relationship}--> {target}")

            return EdgeOperationResponse(
                message="Edge created successfully",
                source=source,
                target=target,
                relationship=relationship,
                total_edges=edges_count
            )

        except Exception as e:
            logger.error(f"❌ [API] 创建关系失败: {e}")
            raise GraphError(
                f"Failed to create edge: {e}",
                error_code=ErrorCode.GRAPH_OPERATION_FAILED
            )


# 全局服务实例
_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """获取记忆服务实例"""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service