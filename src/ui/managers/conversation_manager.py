"""
对话管理器
负责对话的创建、删除、重命名和切换
"""
import time
import uuid
import json
from pathlib import Path
from typing import Dict, List, Optional
from PySide6.QtCore import QObject, Signal
from loguru import logger


class ConversationManager(QObject):
    """对话管理器"""
    
    # 信号定义
    conversation_changed = Signal(str)  # 对话切换
    conversation_list_updated = Signal(list)  # 对话列表更新
    
    def __init__(self, storage_path: Path):
        super().__init__()
        self.storage_path = storage_path / "conversations"
        self.storage_path.mkdir(exist_ok=True, parents=True)
        self.current_conversation_id: Optional[str] = None
        self.conversations: Dict[str, Dict] = {}
        self.load_conversations()
    
    def load_conversations(self):
        """加载所有对话"""
        self.conversations.clear()
        
        for conv_file in self.storage_path.glob("*.json"):
            try:
                with open(conv_file, 'r', encoding='utf-8') as f:
                    conversation = json.load(f)
                    self.conversations[conversation['id']] = conversation
            except Exception as e:
                logger.error(f"加载对话文件 {conv_file} 失败: {e}")
        
        # 按修改时间排序
        sorted_conversations = sorted(
            self.conversations.values(), 
            key=lambda x: x.get('last_modified', 0), 
            reverse=True
        )
        
        self.conversation_list_updated.emit(sorted_conversations)
        
        # 如果没有当前对话，选择最新的（但如果已经有了就不要重复触发）
        if not self.current_conversation_id and sorted_conversations:
            self.current_conversation_id = sorted_conversations[0]['id']
            self.conversation_changed.emit(self.current_conversation_id)
    
    def create_conversation(self, name: str = None) -> str:
        """创建新对话"""
        conv_id = str(uuid.uuid4())
        if not name:
            name = f"新对话 {len(self.conversations) + 1}"
        
        conversation = {
            'id': conv_id,
            'name': name,
            'messages': [],
            'created_time': time.time(),
            'last_modified': time.time(),
            'metadata': {}
        }
        
        self.conversations[conv_id] = conversation
        self._save_conversation(conversation)
        
        # 切换到新对话
        self.current_conversation_id = conv_id
        
        # 重新加载更新列表，但不要触发自动选择逻辑
        self.load_conversations()  
        
        # 手动发出对话切换信号
        self.conversation_changed.emit(conv_id)
        
        return conv_id
    
    def delete_conversation(self, conv_id: str) -> bool:
        """删除对话"""
        try:
            if conv_id in self.conversations:
                # 删除文件
                conv_file = self.storage_path / f"{conv_id}.json"
                if conv_file.exists():
                    conv_file.unlink()
                
                del self.conversations[conv_id]
                
                # 如果删除的是当前对话，切换到其他对话
                if self.current_conversation_id == conv_id:
                    remaining_convs = list(self.conversations.keys())
                    if remaining_convs:
                        self.current_conversation_id = remaining_convs[0]
                        self.conversation_changed.emit(self.current_conversation_id)
                    else:
                        self.current_conversation_id = None
                        self.conversation_changed.emit("")
                
                self.load_conversations()
                return True
                
        except Exception as e:
            logger.error(f"删除对话 {conv_id} 失败: {e}")
            return False
    
    def rename_conversation(self, conv_id: str, new_name: str) -> bool:
        """重命名对话"""
        try:
            if conv_id in self.conversations:
                self.conversations[conv_id]['name'] = new_name
                self.conversations[conv_id]['last_modified'] = time.time()
                self._save_conversation(self.conversations[conv_id])
                self.load_conversations()
                return True
        except Exception as e:
            logger.error(f"重命名对话 {conv_id} 失败: {e}")
            return False
    
    def switch_conversation(self, conv_id: str):
        """切换对话"""
        if conv_id in self.conversations:
            self.current_conversation_id = conv_id
            self.conversation_changed.emit(conv_id)
    
    def get_current_conversation(self) -> Optional[Dict]:
        """获取当前对话"""
        if self.current_conversation_id and self.current_conversation_id in self.conversations:
            return self.conversations[self.current_conversation_id]
        return None
    
    def add_message(self, message: Dict):
        """添加消息到当前对话"""
        conv = self.get_current_conversation()
        if conv:
            message['timestamp'] = time.time()
            conv['messages'].append(message)
            conv['last_modified'] = time.time()
            self._save_conversation(conv)
    
    def clear_current_conversation(self):
        """清空当前对话的消息"""
        conv = self.get_current_conversation()
        if conv:
            conv['messages'].clear()
            conv['last_modified'] = time.time()
            self._save_conversation(conv)
    
    def _save_conversation(self, conversation: Dict):
        """保存单个对话到文件"""
        try:
            conv_file = self.storage_path / f"{conversation['id']}.json"
            with open(conv_file, 'w', encoding='utf-8') as f:
                json.dump(conversation, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存对话失败: {e}")