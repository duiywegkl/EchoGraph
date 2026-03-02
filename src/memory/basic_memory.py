from typing import List, Dict, Any, Optional, Union
from collections import deque
from datetime import datetime
import json
from pathlib import Path
from loguru import logger

class BasicMemory:
    """基础记忆系统 - MVP版本"""
    
    def __init__(
        self,
        max_size: int = 5,
        data_path: Optional[Union[str, Path]] = None,
        auto_load: bool = True,
        max_snapshot_files: int = 20,
    ):
        self.max_size = max_size
        self.conversation_history = deque(maxlen=max_size)  # 统一命名为conversation_history
        self.state_table = {}  # 简单状态表格
        self.data_path = Path(data_path) if data_path else Path("data/memory")
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.max_snapshot_files = max(1, int(max_snapshot_files))
        
        # 向后兼容的别名
        self.hot_memory = self.conversation_history

        if auto_load:
            self.load_latest_from_file()
    
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
        
        self._cleanup_old_snapshots()
        logger.info(f"记忆已保存到: {file_path}")

    def load_latest_from_file(self) -> bool:
        """从最新快照恢复热/温记忆。"""
        snapshots = sorted(self.data_path.glob("memory_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not snapshots:
            return False

        latest = snapshots[0]
        try:
            with open(latest, 'r', encoding='utf-8') as f:
                memory_data = json.load(f)

            conversations = memory_data.get("conversations", [])
            if not isinstance(conversations, list):
                conversations = []
            self.conversation_history.clear()
            for conv in conversations[-self.max_size:]:
                if isinstance(conv, dict):
                    self.conversation_history.append(conv)

            states = memory_data.get("states", {})
            self.state_table = states if isinstance(states, dict) else {}
            logger.info(f"已从快照恢复记忆: {latest}")
            return True
        except Exception as e:
            logger.warning(f"加载记忆快照失败: {latest} | {e}")
            return False

    def _cleanup_old_snapshots(self):
        """保留最近N个快照，避免文件无限增长。"""
        snapshots = sorted(self.data_path.glob("memory_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in snapshots[self.max_snapshot_files:]:
            try:
                stale.unlink()
            except Exception as e:
                logger.debug(f"删除旧记忆快照失败: {stale} | {e}")
