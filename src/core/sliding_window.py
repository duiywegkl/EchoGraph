#!/usr/bin/env python3
"""
滑动窗口对话管理器
解决SillyTavern对话历史不稳定性问题
"""

from collections import deque
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import uuid
from loguru import logger
from dataclasses import dataclass, asdict


@dataclass
class ConversationTurn:
    """单轮对话数据结构"""
    turn_id: str
    sequence: int
    timestamp: datetime
    user_input: str
    llm_response: str
    grag_processed: bool = False
    grag_timestamp: Optional[datetime] = None
    version: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['grag_timestamp'] = self.grag_timestamp.isoformat() if self.grag_timestamp else None
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationTurn':
        """从字典创建实例"""
        data = data.copy()
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        if data['grag_timestamp']:
            data['grag_timestamp'] = datetime.fromisoformat(data['grag_timestamp'])
        return cls(**data)


class SlidingWindowManager:
    """滑动窗口对话管理器"""
    
    def __init__(self, window_size: int = 4, processing_delay: int = 1):
        """
        Args:
            window_size: 滑动窗口大小（保留多少轮对话）
            processing_delay: 处理延迟轮数（延迟多少轮再处理）
        """
        self.window_size = window_size
        self.processing_delay = processing_delay
        self.conversations: deque[ConversationTurn] = deque(maxlen=window_size)
        self.sequence_counter = 0
        self.turn_id_map: Dict[str, ConversationTurn] = {}
        
        logger.info(f"滑动窗口管理器初始化: 窗口大小={window_size}, 延迟={processing_delay}")
    
    def add_turn(self, user_input: str, llm_response: str) -> ConversationTurn:
        """
        添加新的对话轮次
        
        Args:
            user_input: 用户输入
            llm_response: LLM响应
            
        Returns:
            新创建的对话轮次
        """
        self.sequence_counter += 1
        turn = ConversationTurn(
            turn_id=str(uuid.uuid4()),
            sequence=self.sequence_counter,
            timestamp=datetime.now(timezone.utc),
            user_input=user_input,
            llm_response=llm_response
        )
        
        # 如果窗口满了，移除最旧的对话
        if len(self.conversations) >= self.window_size:
            old_turn = self.conversations[0]  # 即将被移除的对话
            if old_turn.turn_id in self.turn_id_map:
                del self.turn_id_map[old_turn.turn_id]
            logger.debug(f"移除旧对话: 序号={old_turn.sequence}, ID={old_turn.turn_id[:8]}")
        
        # 添加新对话到窗口
        self.conversations.append(turn)
        self.turn_id_map[turn.turn_id] = turn
        
        logger.info(f"添加新对话: 序号={turn.sequence}, ID={turn.turn_id[:8]}, 窗口大小={len(self.conversations)}")
        
        return turn
    
    def get_processing_target(self) -> Optional[ConversationTurn]:
        """
        获取需要进行GRAG处理的目标轮次
        
        Returns:
            待处理的对话轮次，如果没有则返回None
        """
        if len(self.conversations) <= self.processing_delay:
            logger.debug(f"对话轮数不足，需要至少{self.processing_delay + 1}轮")
            return None
        
        # 获取倒数第(processing_delay + 1)个对话
        target_index = -(self.processing_delay + 1)
        target_turn = self.conversations[target_index]
        
        if target_turn.grag_processed:
            logger.debug(f"目标轮次已处理: 序号={target_turn.sequence}")
            return None
            
        logger.info(f"找到待处理轮次: 序号={target_turn.sequence}, ID={target_turn.turn_id[:8]}")
        return target_turn
    
    def mark_processed(self, turn_id: str, success: bool = True) -> bool:
        """
        标记对话轮次的处理状态
        
        Args:
            turn_id: 对话轮次ID
            success: 是否处理成功
            
        Returns:
            是否成功标记
        """
        if turn_id not in self.turn_id_map:
            logger.warning(f"未找到对话轮次: {turn_id[:8]}")
            return False
        
        turn = self.turn_id_map[turn_id]
        turn.grag_processed = success
        turn.grag_timestamp = datetime.now(timezone.utc) if success else None
        
        logger.info(f"标记处理状态: 序号={turn.sequence}, 成功={success}")
        return True
    
    def update_turn(self, turn_id: str, user_input: str = None, llm_response: str = None) -> bool:
        """
        更新已存在的对话轮次
        
        Args:
            turn_id: 对话轮次ID
            user_input: 新的用户输入（可选）
            llm_response: 新的LLM响应（可选）
            
        Returns:
            是否成功更新
        """
        if turn_id not in self.turn_id_map:
            logger.warning(f"未找到对话轮次: {turn_id[:8]}")
            return False
        
        turn = self.turn_id_map[turn_id]
        
        # 更新内容
        if user_input is not None:
            turn.user_input = user_input
        if llm_response is not None:
            turn.llm_response = llm_response
        
        # 重置处理状态，因为内容已修改
        turn.grag_processed = False
        turn.grag_timestamp = None
        turn.version += 1
        turn.timestamp = datetime.now(timezone.utc)
        
        logger.info(f"更新对话轮次: 序号={turn.sequence}, 版本={turn.version}")
        return True
    
    def get_recent_context(self, max_turns: int = 3) -> List[ConversationTurn]:
        """
        获取最近的对话上下文
        
        Args:
            max_turns: 最多返回多少轮对话
            
        Returns:
            最近的对话列表
        """
        recent_turns = list(self.conversations)[-max_turns:]
        logger.debug(f"获取最近{len(recent_turns)}轮对话上下文")
        return recent_turns
    
    def get_all_turns(self) -> List[ConversationTurn]:
        """获取窗口内所有对话轮次"""
        return list(self.conversations)
    
    def get_turn_by_id(self, turn_id: str) -> Optional[ConversationTurn]:
        """根据ID获取对话轮次"""
        return self.turn_id_map.get(turn_id)
    
    def is_in_window(self, turn_id: str) -> bool:
        """检查对话轮次是否在滑动窗口内"""
        return turn_id in self.turn_id_map
    
    def get_window_info(self) -> Dict[str, Any]:
        """获取窗口状态信息"""
        processed_count = sum(1 for turn in self.conversations if turn.grag_processed)
        pending_target = self.get_processing_target()
        
        return {
            "window_size": self.window_size,
            "current_turns": len(self.conversations),
            "processed_turns": processed_count,
            "pending_turns": len(self.conversations) - processed_count,
            "next_processing_target": pending_target.turn_id[:8] if pending_target else None,
            "oldest_sequence": self.conversations[0].sequence if self.conversations else None,
            "newest_sequence": self.conversations[-1].sequence if self.conversations else None
        }
    
    def clear_window(self):
        """清空滑动窗口（用于测试或重置）"""
        self.conversations.clear()
        self.turn_id_map.clear()
        self.sequence_counter = 0
        logger.info("滑动窗口已清空")


# 配置类
@dataclass
class SlidingWindowConfig:
    """滑动窗口配置"""
    window_size: int = 4
    processing_delay: int = 1
    max_retries: int = 3
    auto_cleanup_old_turns: bool = True
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'SlidingWindowConfig':
        """从字典创建配置"""
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})