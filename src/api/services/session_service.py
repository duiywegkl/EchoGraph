"""
会话服务层
处理会话相关的业务逻辑
"""

import uuid
import time
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from loguru import logger
from fastapi import BackgroundTasks
from fastapi.responses import StreamingResponse
import io
import json

from ..models.requests import (
    InitializeRequest, AsyncInitializeRequest, ResetSessionRequest
)
from ..models.responses import (
    InitializeResponse, AsyncInitializeResponse, InitTaskStatusResponse,
    SessionStatsResponse, GraphStatusResponse, ExportResponse
)
from ...core.game_engine import GameEngine
from ...core.delayed_update import DelayedUpdateManager
from ...core.conflict_resolver import ConflictResolver
from ...memory import GRAGMemory
from ...core.perception import PerceptionModule
from ...core.rpg_text_processor import RPGTextProcessor
from ...core.validation import ValidationLayer
from ...core.grag_update_agent import GRAGUpdateAgent
from ...core.llm_client import LLMClient
from ...storage import TavernStorageManager
from ...utils.exceptions import SessionError, ErrorCode, ValidationError
from ...utils.enhanced_config import get_config


class InitTaskStatus:
    """初始化任务状态常量"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SessionService:
    """会话服务"""

    def __init__(self):
        self.config = get_config()
        self.storage_manager = TavernStorageManager()
        self.sessions: Dict[str, GameEngine] = {}
        self.sliding_window_managers: Dict[str, DelayedUpdateManager] = {}
        self.conflict_resolvers: Dict[str, ConflictResolver] = {}
        self.initialization_tasks: Dict[str, Dict[str, Any]] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}

    async def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """获取会话锁，确保并发安全"""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    async def initialize_session(self, req: InitializeRequest) -> InitializeResponse:
        """初始化会话"""
        session_id = req.session_id or str(uuid.uuid4())

        async with await self._get_session_lock(session_id):
            try:
                logger.info(f"[START] 开始初始化会话: {session_id}")

                # 检查会话是否已存在
                if session_id in self.sessions:
                    logger.info(f"♻️ 会话 {session_id} 已存在，跳过重复初始化")
                    return await self._get_existing_session_response(session_id)

                # 验证请求数据
                self._validate_initialize_request(req)

                # 注册角色卡（如果不是测试模式）
                if not req.is_test:
                    logger.info("[CHART] 开始注册酒馆角色卡...")
                    local_dir_name = self.storage_manager.register_tavern_character(
                        req.character_card, session_id
                    )
                    logger.info(f"[OK] 已注册酒馆角色: {local_dir_name}")

                # 创建游戏引擎
                engine = await self._create_game_engine(session_id, req.is_test, req.enable_agent)
                self.sessions[session_id] = engine

                # 检查是否需要初始化知识图谱
                existing_nodes = len(engine.memory.knowledge_graph.graph.nodes())
                if existing_nodes > 0:
                    logger.info(f"♻️ 知识图谱已有 {existing_nodes} 个节点，跳过初始化")
                    engine.memory.sync_entities_to_json()
                    return InitializeResponse(
                        session_id=session_id,
                        message=f"使用现有知识图谱，包含 {existing_nodes} 个节点",
                        nodes_added=existing_nodes,
                        edges_added=len(engine.memory.knowledge_graph.graph.edges()),
                        processing_time=0.0
                    )

                # 执行知识图谱初始化
                start_time = time.time()
                init_result = await self._initialize_knowledge_graph(
                    engine, req.character_card, req.world_info
                )
                processing_time = time.time() - start_time

                # 初始化滑动窗口系统
                if req.session_config and req.session_config.get('sliding_window'):
                    await self._initialize_sliding_window(session_id, req.session_config, engine)

                logger.info(f"[SUCCESS] 会话 {session_id} 初始化完成")
                return InitializeResponse(
                    session_id=session_id,
                    message="Session initialized successfully and knowledge graph created.",
                    graph_stats=init_result,
                    processing_time=processing_time
                )

            except Exception as e:
                logger.error(f"❌ 会话初始化失败: {e}")
                # 清理失败的会话
                if session_id in self.sessions:
                    del self.sessions[session_id]
                raise SessionError(
                    f"Failed to initialize session: {e}",
                    session_id=session_id,
                    error_code=ErrorCode.SESSION_CREATION_FAILED
                )

    async def initialize_session_async(
        self, req: AsyncInitializeRequest, background_tasks: BackgroundTasks
    ) -> AsyncInitializeResponse:
        """异步初始化会话"""
        task_id = str(uuid.uuid4())

        # 创建任务记录
        self.initialization_tasks[task_id] = {
            "task_id": task_id,
            "status": InitTaskStatus.PENDING,
            "progress": 0.0,
            "message": "任务已创建，等待执行...",
            "session_id": None,
            "result": None,
            "error": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # 添加后台任务
        background_tasks.add_task(self._perform_async_initialization, task_id, req)

        logger.info(f"[START] 创建异步初始化任务: {task_id}")
        return AsyncInitializeResponse(
            task_id=task_id,
            message="异步初始化任务已创建",
            estimated_time="30-60秒（取决于角色复杂度）"
        )

    async def get_initialization_status(self, task_id: str) -> InitTaskStatusResponse:
        """获取初始化任务状态"""
        if task_id not in self.initialization_tasks:
            raise SessionError(
                f"Task {task_id} not found",
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        task_info = self.initialization_tasks[task_id]
        return InitTaskStatusResponse(**task_info)

    async def get_session_stats(self, session_id: str) -> SessionStatsResponse:
        """获取会话统计信息"""
        if session_id not in self.sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        engine = self.sessions[session_id]
        stats = SessionStatsResponse(
            session_id=session_id,
            graph_nodes=len(engine.memory.knowledge_graph.graph.nodes()),
            graph_edges=len(engine.memory.knowledge_graph.graph.edges()),
            hot_memory_size=len(engine.memory.basic_memory.conversation_history)
        )

        # 添加滑动窗口信息
        if session_id in self.sliding_window_managers:
            sliding_manager = self.sliding_window_managers[session_id]
            stats.sliding_window_size = len(sliding_manager.sliding_window.conversations)
            stats.window_capacity = sliding_manager.sliding_window.window_size
            stats.processing_delay = sliding_manager.sliding_window.processing_delay

        return stats

    async def get_graph_status(self, session_id: str) -> GraphStatusResponse:
        """获取图谱状态"""
        if session_id not in self.sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        engine = self.sessions[session_id]
        total_nodes = len(engine.memory.knowledge_graph.graph.nodes())
        total_edges = len(engine.memory.knowledge_graph.graph.edges())

        # 获取最近更新的节点
        recent_nodes = []
        try:
            for node_id, node_data in list(engine.memory.knowledge_graph.graph.nodes(data=True))[-5:]:
                recent_nodes.append({
                    "id": node_id,
                    "name": node_data.get("name", node_id),
                    "type": node_data.get("type", "unknown")
                })
        except Exception:
            pass

        return GraphStatusResponse(
            session_id=session_id,
            total_nodes=total_nodes,
            total_edges=total_edges,
            recent_nodes=recent_nodes,
            timestamp=time.time()
        )

    async def clear_session_graph(self, session_id: str) -> Dict[str, Any]:
        """清空会话图谱"""
        if session_id not in self.sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        engine = self.sessions[session_id]
        engine.memory.clear_all()
        logger.info(f"会话 {session_id} 的知识图谱已清空")

        return {
            "success": True,
            "message": f"Session {session_id} knowledge graph cleared successfully"
        }

    async def save_session_data(self, session_id: str) -> Dict[str, Any]:
        """保存会话数据"""
        if session_id not in self.sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        engine = self.sessions[session_id]
        start_time = time.time()
        engine.memory.save_all_memory()
        save_time = time.time() - start_time

        total_nodes = len(engine.memory.knowledge_graph.graph.nodes())
        total_edges = len(engine.memory.knowledge_graph.graph.edges())

        return {
            "success": True,
            "session_id": session_id,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "save_time": save_time,
            "message": f"成功保存 {total_nodes} 个节点和 {total_edges} 条边"
        }

    async def reset_session(self, session_id: str, req: ResetSessionRequest) -> Dict[str, Any]:
        """重置会话"""
        if session_id not in self.sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        if req.keep_character_data:
            # 只清除对话历史
            engine = self.sessions[session_id]
            engine.memory.basic_memory.conversation_history.clear()
            logger.info(f"Cleared conversation history for session {session_id}")
        else:
            # 完全重置会话
            del self.sessions[session_id]
            # 清理相关的滑动窗口管理器
            if session_id in self.sliding_window_managers:
                del self.sliding_window_managers[session_id]
            if session_id in self.conflict_resolvers:
                del self.conflict_resolvers[session_id]
            logger.info(f"Completely reset session {session_id}")

        return {"message": "Session reset successfully", "session_id": session_id}

    async def reinitialize_session(self, session_id: str) -> Dict[str, Any]:
        """重新初始化会话 - 完整实现"""
        if session_id not in self.sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        async with await self._get_session_lock(session_id):
            try:
                logger.info(f"🔄 [Re-init] 开始重新初始化会话: {session_id}")
                engine = self.sessions[session_id]

                # 1. 从会话ID反查角色信息
                session_info = self.storage_manager.get_session_info(session_id)
                if not session_info or not session_info.get("character_mapping_key"):
                    logger.error(f"❌ [Re-init] 无法找到会话 {session_id} 的角色映射")
                    raise SessionError(
                        f"Could not determine character for session {session_id}",
                        session_id=session_id,
                        error_code=ErrorCode.SESSION_NOT_FOUND
                    )

                character_id = session_info["character_mapping_key"]
                logger.info(f"✅ [Re-init] 找到角色ID: {character_id}")

                # 2. 获取角色数据
                local_dir_name = session_info["local_dir_name"]
                character_name = session_info.get("character_name", character_id)

                # 从存储路径读取角色数据
                char_path = self.storage_manager.tavern_chars_path / local_dir_name
                character_file = char_path / "character_data.json"

                if not character_file.exists():
                    logger.error(f"❌ [Re-init] 角色数据文件不存在: {character_file}")
                    raise SessionError(
                        f"Character data file not found for {character_id}",
                        session_id=session_id,
                        error_code=ErrorCode.SESSION_NOT_FOUND
                    )

                try:
                    with open(character_file, 'r', encoding='utf-8') as f:
                        character_card = json.load(f)
                except Exception as e:
                    logger.error(f"❌ [Re-init] 读取角色数据失败: {e}")
                    raise SessionError(
                        f"Failed to read character data: {e}",
                        session_id=session_id,
                        error_code=ErrorCode.SESSION_OPERATION_FAILED
                    )

                # 获取世界书信息（如果有的话）
                world_info = ""  # 暂时设为空，可以后续从其他地方获取

                logger.info(f"✅ [Re-init] 获取到角色数据: {character_name}")

                # 3. 清空现有知识图谱
                logger.info(f"🧹 [Re-init] 清空现有知识图谱...")
                old_nodes = len(engine.memory.knowledge_graph.graph.nodes())
                old_edges = len(engine.memory.knowledge_graph.graph.edges())
                engine.memory.clear_all()
                logger.info(f"🧹 [Re-init] 已清空 {old_nodes} 个节点和 {old_edges} 个边")

                # 4. 重新初始化知识图谱
                logger.info(f"🧠 [Re-init] 重新初始化知识图谱...")
                start_time = time.time()

                # 使用线程池执行耗时的LLM初始化
                from concurrent.futures import ThreadPoolExecutor
                import asyncio

                def sync_initialize():
                    return engine.initialize_from_tavern_data(character_card, world_info)

                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor() as executor:
                    init_result = await loop.run_in_executor(executor, sync_initialize)

                processing_time = time.time() - start_time

                # 5. 获取新的图谱统计
                new_nodes = len(engine.memory.knowledge_graph.graph.nodes())
                new_edges = len(engine.memory.knowledge_graph.graph.edges())

                logger.info(f"🎉 [Re-init] 重新初始化完成: {new_nodes} 个节点, {new_edges} 个边")

                # 6. 发送WebSocket通知给前端
                try:
                    from ..websocket.manager import get_connection_manager
                    manager = get_connection_manager()
                    await manager.send_message(session_id, {
                        "type": "graph_updated",
                        "message": f"知识图谱已重新初始化: {character_name}",
                        "session_id": session_id,
                        "character_name": character_name,
                        "nodes_updated": new_nodes,
                        "edges_added": new_edges,
                        "processing_time": processing_time,
                        "reinitialize_completed": True
                    })
                    logger.info(f"✅ [Re-init] 已发送WebSocket通知给前端")
                except Exception as e:
                    logger.warning(f"⚠️ [Re-init] 发送WebSocket通知失败: {e}")

                return {
                    "message": "Session reinitialized successfully",
                    "session_id": session_id,
                    "character_name": character_name,
                    "character_id": character_id,
                    "nodes_created": new_nodes,
                    "edges_created": new_edges,
                    "processing_time": processing_time,
                    "old_stats": {"nodes": old_nodes, "edges": old_edges},
                    "new_stats": {"nodes": new_nodes, "edges": new_edges}
                }

            except Exception as e:
                logger.error(f"❌ [Re-init] 重新初始化失败: {e}")
                raise SessionError(
                    f"Failed to reinitialize session: {e}",
                    session_id=session_id,
                    error_code=ErrorCode.SESSION_OPERATION_FAILED
                )

    async def list_sessions(self) -> Dict[str, Any]:
        """列出所有会话"""
        session_list = []
        for sid, engine in self.sessions.items():
            session_list.append({
                "session_id": sid,
                "graph_nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                "graph_edges": len(engine.memory.knowledge_graph.graph.edges()),
                "conversation_turns": len(engine.memory.basic_memory.conversation_history)
            })

        return {"sessions": session_list, "total_sessions": len(self.sessions)}

    async def export_session_graph(self, session_id: str) -> StreamingResponse:
        """导出会话图谱"""
        if session_id not in self.sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id,
                error_code=ErrorCode.SESSION_NOT_FOUND
            )

        engine = self.sessions[session_id]

        # 转换为JSON格式
        import networkx as nx
        from networkx.readwrite import json_graph

        graph_data = json_graph.node_link_data(engine.memory.knowledge_graph.graph)

        export_data = ExportResponse(
            session_id=session_id,
            export_timestamp=datetime.utcnow().isoformat(),
            graph_stats={
                "nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                "edges": len(engine.memory.knowledge_graph.graph.edges())
            },
            graph_data=graph_data
        )

        # 创建JSON流
        json_str = export_data.model_dump_json(indent=2, ensure_ascii=False)
        json_bytes = json_str.encode('utf-8')

        return StreamingResponse(
            io.BytesIO(json_bytes),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=echograph-graph-export.json"
            }
        )

    # 私有方法

    def _validate_initialize_request(self, req: InitializeRequest):
        """验证初始化请求"""
        if not req.character_card:
            raise ValidationError("Character card is required")

        # 验证角色卡必要字段
        required_fields = ['name']
        for field in required_fields:
            if field not in req.character_card:
                raise ValidationError(f"Character card missing required field: {field}")

    async def _get_existing_session_response(self, session_id: str) -> InitializeResponse:
        """获取现有会话的响应"""
        engine = self.sessions[session_id]
        nodes_count = len(engine.memory.knowledge_graph.graph.nodes())
        edges_count = len(engine.memory.knowledge_graph.graph.edges())

        return InitializeResponse(
            session_id=session_id,
            message=f"使用现有会话，当前包含 {nodes_count} 个节点和 {edges_count} 条边",
            nodes_added=nodes_count,
            edges_added=edges_count,
            processing_time=0.0
        )

    async def _create_game_engine(self, session_id: str, is_test: bool, enable_agent: bool) -> GameEngine:
        """创建游戏引擎"""
        from fastapi.concurrency import run_in_threadpool

        if not enable_agent:
            logger.warning("⚠️ 收到 enable_agent=False 请求，按策略强制启用LLM Agent。")
        enable_agent = True

        logger.info(f"⚙️ 创建会话引擎: {session_id}")

        def _create_engine():
            # 获取图谱文件路径
            graph_path = self.storage_manager.get_graph_file_path(session_id, is_test)
            entities_json_path = str(Path(graph_path).parent / "entities.json")

            # 初始化核心组件
            # 注意力机制配置
            attention_config = {
                'collective_weight': 0.6,
                'holistic_weight': 0.4,
                'importance_threshold': 0.3,
                'max_context_entities': 15
            }

            memory = GRAGMemory(
                graph_save_path=graph_path,
                entities_json_path=entities_json_path,
                auto_load_entities=True,
                attention_config=attention_config
            )
            perception = PerceptionModule()
            rpg_processor = RPGTextProcessor()
            validation_layer = ValidationLayer()

            # 可选初始化GRAG Agent
            grag_agent = None
            if enable_agent:
                try:
                    if not self.config.llm.api_key or not self.config.llm.base_url:
                        logger.warning("[WARN] LLM配置不完整，禁用GRAG Agent")
                    else:
                        llm_client = LLMClient()
                        grag_agent = GRAGUpdateAgent(llm_client)
                        logger.info("[OK] GRAG Agent初始化成功")
                except Exception as e:
                    logger.warning(f"[WARN] GRAG Agent初始化失败: {e}")

            return GameEngine(memory, perception, rpg_processor, validation_layer, grag_agent)

        engine = await run_in_threadpool(_create_engine)
        logger.info("[OK] 游戏引擎创建成功")
        return engine

    async def _initialize_knowledge_graph(
        self, engine: GameEngine, character_card: Dict[str, Any], world_info: str
    ) -> Dict[str, Any]:
        """初始化知识图谱"""
        from fastapi.concurrency import run_in_threadpool

        logger.info("[AI] 开始知识图谱初始化...")

        try:
            init_result = await run_in_threadpool(
                engine.initialize_from_tavern_data, character_card, world_info
            )
            logger.info(f"[OK] 知识图谱初始化完成: {init_result}")
            return init_result
        except Exception as e:
            logger.error(f"❌ 知识图谱初始化失败: {e}")
            return {
                "nodes_added": 0,
                "edges_added": 0,
                "method": "failed",
                "error": str(e)
            }

    async def _initialize_sliding_window(
        self, session_id: str, session_config: Dict[str, Any], engine: GameEngine
    ):
        """初始化滑动窗口系统"""
        logger.info("🔄 初始化滑动窗口系统...")
        try:
            sliding_config = session_config.get('sliding_window', {})
            window_size = sliding_config.get('window_size', 4)
            processing_delay = sliding_config.get('processing_delay', 1)
            enable_enhanced_agent = sliding_config.get('enable_enhanced_agent', True)

            from ...core.sliding_window import SlidingWindowManager
            sliding_window = SlidingWindowManager(
                window_size=window_size,
                processing_delay=processing_delay
            )

            sliding_window_manager = DelayedUpdateManager(
                sliding_window=sliding_window,
                memory=engine.memory,
                grag_agent=engine.grag_agent if enable_enhanced_agent else None
            )

            self.sliding_window_managers[session_id] = sliding_window_manager

            # 创建冲突解决器
            conflict_resolver = ConflictResolver(sliding_window, sliding_window_manager)
            self.conflict_resolvers[session_id] = conflict_resolver

            logger.info(f"[OK] 滑动窗口系统初始化成功: {session_id}")
        except Exception as e:
            logger.warning(f"[WARN] 滑动窗口系统初始化失败: {e}")

    async def _perform_async_initialization(self, task_id: str, req: AsyncInitializeRequest):
        """执行异步初始化"""
        logger.info(f"🔄 [Async Task {task_id}] 开始后台初始化")
        try:
            # 更新任务状态
            self.initialization_tasks[task_id].update({
                "status": InitTaskStatus.RUNNING,
                "progress": 0.1,
                "message": "开始初始化会话...",
                "updated_at": datetime.now().isoformat()
            })

            # 转换为同步请求并执行
            sync_req = InitializeRequest(
                session_id=req.session_id,
                character_card=req.character_card,
                world_info=req.world_info,
                session_config=req.session_config,
                is_test=req.is_test,
                enable_agent=req.enable_agent
            )

            result = await self.initialize_session(sync_req)

            # 更新任务完成状态
            self.initialization_tasks[task_id].update({
                "status": InitTaskStatus.COMPLETED,
                "progress": 1.0,
                "message": "初始化完成",
                "session_id": result.session_id,
                "result": result.model_dump(),
                "updated_at": datetime.now().isoformat()
            })

            logger.info(f"[SUCCESS] [Async Task {task_id}] 异步初始化完成")

        except Exception as e:
            logger.error(f"❌ [Async Task {task_id}] 异步初始化失败: {e}")
            self.initialization_tasks[task_id].update({
                "status": InitTaskStatus.FAILED,
                "error": str(e),
                "updated_at": datetime.now().isoformat()
            })


# 全局服务实例
_session_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    """获取会话服务实例"""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
