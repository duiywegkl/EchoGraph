from typing import List, Dict, Any
from collections import deque
from datetime import datetime
import json
from pathlib import Path
from loguru import logger

class BasicMemory:
    """基础记忆系统 - MVP版本"""
    
    def __init__(self, max_size: int = 5):
        self.max_size = max_size
        self.conversation_history = deque(maxlen=max_size)  # 统一命名为conversation_history
        self.state_table = {}  # 简单状态表格
        self.data_path = Path("data/memory")
        self.data_path.mkdir(parents=True, exist_ok=True)
        
        # 向后兼容的别名
        self.hot_memory = self.conversation_history
    
    def add_conversation(self, user_input: str, ai_response: str):
        """添加对话到热记忆"""
        conversation = {
            "timestamp": datetime.now().isoformat(),
            "user": user_input,
            "ai": ai_response
        }
        self.conversation_history.append(conversation)
        logger.info(f"添加对话到记忆，当前记忆条目：{len(self.conversation_history)}")
    
    def get_context(self, recent_turns: int = 3) -> str:
        """获取最近对话上下文"""
        recent_conversations = list(self.conversation_history)[-recent_turns:]
        
        context_parts = []
        for conv in recent_conversations:
            context_parts.append(f"用户: {conv['user']}")
            context_parts.append(f"AI: {conv['ai']}")
        
        return "\n".join(context_parts)
    
    def update_state(self, key: str, value: Any):
        """更新状态表格"""
        self.state_table[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        logger.info(f"更新状态: {key} = {value}")
    
    def get_state(self, key: str) -> Any:
        """获取状态值"""
        return self.state_table.get(key, {}).get("value")
    
    def save_to_file(self):
        """保存记忆到文件"""
        memory_data = {
            "conversations": list(self.conversation_history),
            "states": self.state_table
        }
        
        file_path = self.data_path / f"memory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(memory_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"记忆已保存到: {file_path}")
