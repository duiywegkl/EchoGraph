#!/usr/bin/env python3
"""
延迟更新管理器 - 处理滑动窗口的GRAG更新逻辑
"""

from typing import Dict, Any, Optional, List
from loguru import logger
from datetime import datetime

from .sliding_window import SlidingWindowManager, ConversationTurn
from .grag_update_agent import GRAGUpdateAgent
from src.memory import GRAGMemory


class DelayedUpdateManager:
    """延迟更新管理器"""
    
    def __init__(self, 
                 sliding_window: SlidingWindowManager,
                 grag_agent: Optional[GRAGUpdateAgent] = None,
                 memory: Optional[GRAGMemory] = None):
        """
        Args:
            sliding_window: 滑动窗口管理器
            grag_agent: GRAG更新Agent（可选）
            memory: GRAG内存系统（可选）
        """
        self.sliding_window = sliding_window
        self.grag_agent = grag_agent
        self.memory = memory
        self.update_stats = {
            "total_updates_attempted": 0,
            "successful_updates": 0,
            "failed_updates": 0,
            "skipped_updates": 0
        }
        
        logger.info("延迟更新管理器初始化完成")
    
    def process_new_conversation(self, user_input: str, llm_response: str) -> Dict[str, Any]:
        """
        处理新的对话轮次，可能触发延迟更新
        
        Args:
            user_input: 用户输入
            llm_response: LLM响应
            
        Returns:
            处理结果统计
        """
        # 1. 添加新对话到滑动窗口
        new_turn = self.sliding_window.add_turn(user_input, llm_response)
        logger.info(f"新对话已添加到滑动窗口: {new_turn.turn_id[:8]}")
        
        # 2. 检查是否有需要处理的目标轮次
        target_turn = self.sliding_window.get_processing_target()
        
        result = {
            "new_turn_id": new_turn.turn_id,
            "new_turn_sequence": new_turn.sequence,
            "target_processed": False,
            "grag_updates": {},
            "window_info": self.sliding_window.get_window_info()
        }
        
        if target_turn:
            logger.info(f"触发延迟更新: 目标轮次={target_turn.sequence}")
            update_result = self._process_target_turn(target_turn)
            result["target_processed"] = True
            result["grag_updates"] = update_result
        else:
            logger.debug("无需要处理的目标轮次")
            result["grag_updates"] = {"reason": "no_target", "updates": {}}
        
        return result
    
    def _process_target_turn(self, target_turn: ConversationTurn) -> Dict[str, Any]:
        """
        处理目标对话轮次的GRAG更新
        
        Args:
            target_turn: 要处理的对话轮次
            
        Returns:
            更新结果
        """
        self.update_stats["total_updates_attempted"] += 1
        
        try:
            logger.info(f"开始处理目标轮次: 序号={target_turn.sequence}, ID={target_turn.turn_id[:8]}")
            
            # 获取最近的对话上下文
            recent_context = self.sliding_window.get_recent_context(max_turns=3)
            context_text = self._build_context_text(recent_context)
            
            if self.grag_agent and self.memory:
                # 使用Agent进行智能分析
                result = self._process_with_agent(target_turn, context_text)
            else:
                # 回退到简单记录
                result = self._process_without_agent(target_turn)
                logger.warning("未配置GRAG Agent，使用简单处理模式")
            
            # 标记处理完成
            success = result.get("success", False)
            self.sliding_window.mark_processed(target_turn.turn_id, success)
            
            if success:
                self.update_stats["successful_updates"] += 1
            else:
                self.update_stats["failed_updates"] += 1
            
            logger.info(f"目标轮次处理完成: 成功={success}")
            return result
            
        except Exception as e:
            logger.error(f"处理目标轮次时出错: {e}")
            self.update_stats["failed_updates"] += 1
            self.sliding_window.mark_processed(target_turn.turn_id, False)
            return {
                "success": False,
                "error": str(e),
                "updates": {}
            }
    
    def _process_with_agent(self, target_turn: ConversationTurn, context_text: str) -> Dict[str, Any]:
        """
        使用GRAG Agent处理目标轮次
        
        Args:
            target_turn: 目标轮次
            context_text: 上下文文本
            
        Returns:
            处理结果
        """
        try:
            logger.info("使用GRAG Agent进行智能分析...")
            
            # 调用Agent分析
            analysis_result = self.grag_agent.analyze_conversation_for_updates(
                user_input=target_turn.user_input,
                llm_response=target_turn.llm_response,
                current_graph=self.memory.knowledge_graph,
                recent_context=context_text
            )
            
            if "error" in analysis_result:
                logger.warning(f"Agent分析失败: {analysis_result['error']}")
                return {
                    "success": False,
                    "reason": "agent_analysis_failed",
                    "error": analysis_result["error"],
                    "updates": {}
                }
            
            # 转换为执行格式
            execution_format = self.grag_agent.convert_to_execution_format(analysis_result)
            
            # 应用更新（这里需要集成到现有的更新逻辑）
            update_count = self._apply_updates(execution_format)
            
            return {
                "success": True,
                "method": "grag_agent",
                "operations_analyzed": len(analysis_result.get("operations", [])),
                "updates_applied": update_count,
                "updates": execution_format
            }
            
        except Exception as e:
            logger.error(f"Agent处理过程出错: {e}")
            return {
                "success": False,
                "reason": "agent_processing_error",
                "error": str(e),
                "updates": {}
            }
    
    def _process_without_agent(self, target_turn: ConversationTurn) -> Dict[str, Any]:
        """
        不使用Agent的简单处理模式
        
        Args:
            target_turn: 目标轮次
            
        Returns:
            处理结果
        """
        logger.info("使用简单处理模式")
        
        # 简单记录对话，不进行GRAG更新
        if self.memory:
            self.memory.add_conversation(target_turn.user_input, target_turn.llm_response)
        
        return {
            "success": True,
            "method": "simple_storage",
            "updates_applied": 0,
            "updates": {
                "conversation_stored": True,
                "grag_analysis": False
            }
        }
    
    def _build_context_text(self, recent_turns: List[ConversationTurn]) -> str:
        """
        构建上下文文本
        
        Args:
            recent_turns: 最近的对话轮次列表
            
        Returns:
            上下文文本
        """
        context_parts = []
        for turn in recent_turns:
            context_parts.append(f"用户: {turn.user_input}")
            context_parts.append(f"助手: {turn.llm_response}")
        
        context_text = "\n".join(context_parts)
        logger.debug(f"构建上下文文本: {len(context_text)} 字符")
        return context_text
    
    def _apply_updates(self, execution_format: Dict[str, Any]) -> int:
        """
        应用GRAG更新（这里是简化版，需要与现有系统集成）
        
        Args:
            execution_format: 执行格式的更新指令
            
        Returns:
            应用的更新数量
        """
        if not self.memory:
            logger.warning("未配置GRAG内存系统，跳过更新应用")
            return 0
        
        update_count = 0
        
        # 应用节点更新
        for node_update in execution_format.get("nodes_to_update", []):
            try:
                node_id = node_update.get("node_id")
                node_type = node_update.get("type", "unknown")
                attributes = node_update.get("attributes", {})
                
                self.memory.add_or_update_node(node_id, node_type, **attributes)
                update_count += 1
                logger.debug(f"应用节点更新: {node_id}")
                
            except Exception as e:
                logger.warning(f"节点更新失败: {e}")
        
        # 应用边更新
        for edge_add in execution_format.get("edges_to_add", []):
            try:
                source = edge_add.get("source")
                target = edge_add.get("target")
                relationship = edge_add.get("relationship")
                
                self.memory.add_edge(source, target, relationship)
                update_count += 1
                logger.debug(f"应用边更新: {source} -> {target}")
                
            except Exception as e:
                logger.warning(f"边更新失败: {e}")
        
        logger.info(f"共应用 {update_count} 个更新")
        return update_count
    
    def handle_conversation_modification(self, turn_id: str, user_input: str = None, llm_response: str = None) -> Dict[str, Any]:
        """
        处理对话修改（来自SillyTavern的编辑操作）
        
        Args:
            turn_id: 对话轮次ID
            user_input: 新的用户输入（可选）
            llm_response: 新的LLM响应（可选）
            
        Returns:
            处理结果
        """
        if not self.sliding_window.is_in_window(turn_id):
            logger.info(f"对话轮次不在滑动窗口内，忽略修改: {turn_id[:8]}")
            return {
                "success": True,
                "reason": "out_of_window",
                "action": "ignored"
            }
        
        # 更新对话内容
        success = self.sliding_window.update_turn(turn_id, user_input, llm_response)
        
        if success:
            logger.info(f"对话轮次已更新: {turn_id[:8]}")
            # 注意：更新后的轮次会被标记为未处理，等待下次延迟更新
        
        return {
            "success": success,
            "action": "updated" if success else "failed",
            "turn_id": turn_id
        }
    
    def get_update_stats(self) -> Dict[str, Any]:
        """获取更新统计信息"""
        window_info = self.sliding_window.get_window_info()
        
        return {
            **self.update_stats,
            "window_info": window_info,
            "success_rate": (
                self.update_stats["successful_updates"] / max(1, self.update_stats["total_updates_attempted"])
            ) * 100
        }
    
    def reset_stats(self):
        """重置统计信息"""
        self.update_stats = {
            "total_updates_attempted": 0,
            "successful_updates": 0,
            "failed_updates": 0,
            "skipped_updates": 0
        }
        logger.info("更新统计信息已重置")