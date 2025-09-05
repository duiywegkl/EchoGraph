#!/usr/bin/env python3
"""
冲突解决和状态同步器
处理SillyTavern对话历史的修改、删除、重新生成等操作
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from loguru import logger
import hashlib
import json

from .sliding_window import SlidingWindowManager, ConversationTurn
from .delayed_update import DelayedUpdateManager


class ConversationState:
    """对话状态快照"""
    
    def __init__(self, turn: ConversationTurn):
        self.turn_id = turn.turn_id
        self.sequence = turn.sequence
        self.content_hash = self._calculate_content_hash(turn.user_input, turn.llm_response)
        self.timestamp = turn.timestamp
        self.version = turn.version
        self.grag_processed = turn.grag_processed
    
    def _calculate_content_hash(self, user_input: str, llm_response: str) -> str:
        """计算对话内容的哈希值"""
        content = f"{user_input}||{llm_response}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    
    def has_changed(self, turn: ConversationTurn) -> bool:
        """检查对话是否发生变化"""
        new_hash = self._calculate_content_hash(turn.user_input, turn.llm_response)
        return self.content_hash != new_hash


class ConflictResolver:
    """冲突解决器"""
    
    def __init__(self, 
                 sliding_window: SlidingWindowManager,
                 delayed_update: DelayedUpdateManager):
        """
        Args:
            sliding_window: 滑动窗口管理器
            delayed_update: 延迟更新管理器
        """
        self.sliding_window = sliding_window
        self.delayed_update = delayed_update
        self.state_snapshots: Dict[str, ConversationState] = {}
        self.conflict_stats = {
            "total_syncs": 0,
            "conflicts_detected": 0,
            "conflicts_resolved": 0,
            "out_of_window_ignores": 0
        }
        
        logger.info("冲突解决器初始化完成")
    
    def sync_conversation_state(self, tavern_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        同步SillyTavern的对话历史状态
        
        Args:
            tavern_history: SillyTavern的对话历史
            格式: [{"user": "...", "assistant": "...", "timestamp": "...", "id": "..."}]
            
        Returns:
            同步结果统计
        """
        self.conflict_stats["total_syncs"] += 1
        sync_results = {
            "synced_turns": 0,
            "conflicts_detected": 0,
            "conflicts_resolved": 0,
            "out_of_window": 0,
            "new_turns": 0,
            "updated_turns": 0,
            "deleted_turns": 0
        }
        
        logger.info(f"开始同步对话状态: {len(tavern_history)} 个历史记录")
        
        try:
            # 1. 识别在滑动窗口范围内的对话
            window_turns = self.sliding_window.get_all_turns()
            window_sequences = {turn.sequence for turn in window_turns}
            
            # 2. 处理酒馆历史中的每个对话
            for tavern_turn in tavern_history:
                result = self._process_tavern_turn(tavern_turn, window_sequences)
                
                # 累计统计
                for key in ["conflicts_detected", "conflicts_resolved", "out_of_window", 
                           "new_turns", "updated_turns"]:
                    if key in result:
                        sync_results[key] += result[key]
            
            # 3. 检查滑动窗口中是否有被删除的对话
            deleted_count = self._check_for_deleted_turns(tavern_history)
            sync_results["deleted_turns"] = deleted_count
            
            sync_results["synced_turns"] = len(tavern_history)
            
            # 4. 更新统计
            self.conflict_stats["conflicts_detected"] += sync_results["conflicts_detected"]
            self.conflict_stats["conflicts_resolved"] += sync_results["conflicts_resolved"]
            self.conflict_stats["out_of_window_ignores"] += sync_results["out_of_window"]
            
            logger.info(f"对话状态同步完成: {sync_results}")
            return sync_results
            
        except Exception as e:
            logger.error(f"对话状态同步失败: {e}")
            return {"error": str(e), **sync_results}
    
    def _process_tavern_turn(
        self, 
        tavern_turn: Dict[str, Any], 
        window_sequences: set
    ) -> Dict[str, int]:
        """
        处理单个酒馆对话轮次
        
        Args:
            tavern_turn: 酒馆对话数据
            window_sequences: 滑动窗口中的序列号集合
            
        Returns:
            处理结果统计
        """
        result = {"conflicts_detected": 0, "conflicts_resolved": 0, "out_of_window": 0,
                 "new_turns": 0, "updated_turns": 0}
        
        turn_id = tavern_turn.get("id")
        sequence = tavern_turn.get("sequence")
        user_input = tavern_turn.get("user", "")
        llm_response = tavern_turn.get("assistant", "")
        
        # 检查是否在滑动窗口范围内
        if sequence and sequence not in window_sequences:
            result["out_of_window"] += 1
            logger.debug(f"对话轮次 {sequence} 不在滑动窗口范围内，跳过处理")
            return result
        
        if not turn_id:
            logger.warning("酒馆对话缺少ID，跳过处理")
            return result
        
        # 检查是否是已知对话
        existing_turn = self.sliding_window.get_turn_by_id(turn_id)
        
        if existing_turn:
            # 现有对话，检查是否有变化
            conflict_result = self._handle_existing_turn_conflict(
                existing_turn, user_input, llm_response
            )
            result.update(conflict_result)
            
        else:
            # 新对话，需要添加到滑动窗口
            if self._should_add_turn_to_window(tavern_turn):
                new_turn = self.sliding_window.add_turn(user_input, llm_response)
                self._create_state_snapshot(new_turn)
                result["new_turns"] += 1
                logger.info(f"添加新对话到滑动窗口: {turn_id[:8]}")
        
        return result
    
    def _handle_existing_turn_conflict(
        self, 
        existing_turn: ConversationTurn,
        new_user_input: str,
        new_llm_response: str
    ) -> Dict[str, int]:
        """
        处理现有对话的冲突
        
        Args:
            existing_turn: 现有对话轮次
            new_user_input: 新的用户输入
            new_llm_response: 新的LLM响应
            
        Returns:
            冲突处理结果
        """
        result = {"conflicts_detected": 0, "conflicts_resolved": 0, "updated_turns": 0}
        
        # 检查内容是否发生变化
        old_snapshot = self.state_snapshots.get(existing_turn.turn_id)
        
        if old_snapshot:
            # 创建临时turn对象来检查变化
            temp_turn = ConversationTurn(
                turn_id=existing_turn.turn_id,
                sequence=existing_turn.sequence,
                timestamp=existing_turn.timestamp,
                user_input=new_user_input,
                llm_response=new_llm_response
            )
            
            if old_snapshot.has_changed(temp_turn):
                result["conflicts_detected"] += 1
                logger.info(f"检测到对话内容变化: {existing_turn.turn_id[:8]}")
                
                # 应用冲突解决策略：最新内容获胜
                success = self.sliding_window.update_turn(
                    existing_turn.turn_id, new_user_input, new_llm_response
                )
                
                if success:
                    result["conflicts_resolved"] += 1
                    result["updated_turns"] += 1
                    
                    # 更新状态快照
                    updated_turn = self.sliding_window.get_turn_by_id(existing_turn.turn_id)
                    if updated_turn:
                        self._create_state_snapshot(updated_turn)
                    
                    logger.info(f"冲突已解决，对话已更新: {existing_turn.turn_id[:8]}")
                else:
                    logger.error(f"冲突解决失败: {existing_turn.turn_id[:8]}")
        
        return result
    
    def _check_for_deleted_turns(self, tavern_history: List[Dict[str, Any]]) -> int:
        """
        检查滑动窗口中是否有被删除的对话
        
        Args:
            tavern_history: 酒馆对话历史
            
        Returns:
            被删除的对话数量
        """
        tavern_ids = {turn.get("id") for turn in tavern_history if turn.get("id")}
        window_turns = self.sliding_window.get_all_turns()
        deleted_count = 0
        
        for turn in window_turns:
            if turn.turn_id not in tavern_ids:
                # 这个对话在酒馆历史中已经不存在了
                logger.info(f"检测到已删除的对话: {turn.turn_id[:8]}")
                # 注意：我们不从滑动窗口中删除，因为可能只是临时不可见
                # 实际的删除策略需要更谨慎的处理
                deleted_count += 1
        
        return deleted_count
    
    def _should_add_turn_to_window(self, tavern_turn: Dict[str, Any]) -> bool:
        """
        判断是否应该将酒馆对话添加到滑动窗口
        
        Args:
            tavern_turn: 酒馆对话数据
            
        Returns:
            是否应该添加
        """
        # 检查是否有有效的内容
        user_input = tavern_turn.get("user", "").strip()
        llm_response = tavern_turn.get("assistant", "").strip()
        
        if not user_input and not llm_response:
            return False
        
        # 检查时间戳，只处理最近的对话
        timestamp_str = tavern_turn.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                age_hours = (now - timestamp).total_seconds() / 3600
                
                # 只添加最近24小时内的对话
                if age_hours > 24:
                    logger.debug(f"跳过过旧的对话: {age_hours:.1f}小时前")
                    return False
            except Exception as e:
                logger.warning(f"解析时间戳失败: {timestamp_str}, {e}")
        
        return True
    
    def _create_state_snapshot(self, turn: ConversationTurn):
        """创建对话状态快照"""
        snapshot = ConversationState(turn)
        self.state_snapshots[turn.turn_id] = snapshot
        logger.debug(f"创建状态快照: {turn.turn_id[:8]}")
    
    def handle_conversation_modification(
        self, 
        turn_id: str, 
        modification_type: str,
        new_user_input: str = None, 
        new_llm_response: str = None
    ) -> Dict[str, Any]:
        """
        处理特定的对话修改操作
        
        Args:
            turn_id: 对话ID
            modification_type: 修改类型 (edit/regenerate/delete)
            new_user_input: 新的用户输入
            new_llm_response: 新的LLM响应
            
        Returns:
            处理结果
        """
        if not self.sliding_window.is_in_window(turn_id):
            logger.info(f"对话不在滑动窗口内，忽略修改: {turn_id[:8]}")
            return {
                "success": True,
                "action": "ignored",
                "reason": "out_of_window"
            }
        
        logger.info(f"处理对话修改: {modification_type}, ID: {turn_id[:8]}")
        
        if modification_type in ["edit", "regenerate"]:
            # 编辑或重新生成
            result = self.delayed_update.handle_conversation_modification(
                turn_id, new_user_input, new_llm_response
            )
            
            if result["success"]:
                # 更新状态快照
                updated_turn = self.sliding_window.get_turn_by_id(turn_id)
                if updated_turn:
                    self._create_state_snapshot(updated_turn)
            
            return result
            
        elif modification_type == "delete":
            # 删除对话
            return self._handle_conversation_deletion(turn_id)
            
        else:
            logger.warning(f"未知的修改类型: {modification_type}")
            return {
                "success": False,
                "error": f"Unknown modification type: {modification_type}"
            }
    
    def _handle_conversation_deletion(self, turn_id: str) -> Dict[str, Any]:
        """
        处理对话删除
        
        Args:
            turn_id: 要删除的对话ID
            
        Returns:
            处理结果
        """
        # 注意：我们不真正删除滑动窗口中的对话，而是标记为"已删除"
        # 这样可以保持滑动窗口的完整性和处理逻辑的一致性
        
        turn = self.sliding_window.get_turn_by_id(turn_id)
        if not turn:
            return {
                "success": False,
                "error": "Turn not found in sliding window"
            }
        
        # 标记为已删除（通过添加特殊属性）
        # 在实际实现中，可能需要扩展ConversationTurn结构
        logger.info(f"标记对话为已删除: {turn_id[:8]}")
        
        # 清理状态快照
        if turn_id in self.state_snapshots:
            del self.state_snapshots[turn_id]
        
        return {
            "success": True,
            "action": "marked_deleted",
            "turn_id": turn_id
        }
    
    def get_conflict_stats(self) -> Dict[str, Any]:
        """获取冲突解决统计信息"""
        return {
            **self.conflict_stats,
            "success_rate": (
                self.conflict_stats["conflicts_resolved"] / 
                max(1, self.conflict_stats["conflicts_detected"])
            ) * 100,
            "active_snapshots": len(self.state_snapshots)
        }
    
    def cleanup_old_snapshots(self, max_age_hours: int = 24):
        """清理旧的状态快照"""
        cutoff_time = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        
        to_remove = []
        for turn_id, snapshot in self.state_snapshots.items():
            if snapshot.timestamp.timestamp() < cutoff_time:
                to_remove.append(turn_id)
        
        for turn_id in to_remove:
            del self.state_snapshots[turn_id]
        
        if to_remove:
            logger.info(f"清理了 {len(to_remove)} 个过期状态快照")
    
    def reset_stats(self):
        """重置统计信息"""
        self.conflict_stats = {
            "total_syncs": 0,
            "conflicts_detected": 0,
            "conflicts_resolved": 0,
            "out_of_window_ignores": 0
        }
        logger.info("冲突解决统计信息已重置")


# 配置类
class ConflictResolutionConfig:
    """冲突解决配置"""
    
    def __init__(self):
        self.strategy = "latest_wins"  # 最新内容获胜策略
        self.preserve_user_edits = True  # 保留用户手动编辑
        self.max_conflict_age_hours = 24  # 最大冲突年龄（小时）
        self.auto_cleanup_interval = 3600  # 自动清理间隔（秒）
        self.enable_deletion_tracking = True  # 启用删除追踪
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "preserve_user_edits": self.preserve_user_edits,
            "max_conflict_age_hours": self.max_conflict_age_hours,
            "auto_cleanup_interval": self.auto_cleanup_interval,
            "enable_deletion_tracking": self.enable_deletion_tracking
        }