"""
SillyTavern专用存储管理器
负责按酒馆角色卡分类管理GRAG记忆数据，支持多会话和测试环境
"""
import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from loguru import logger

class TavernStorageManager:
    """酒馆角色卡分类存储管理器"""
    
    def __init__(self, base_path: str = "data"):
        self.base_path = Path(base_path)
        self.tavern_chars_path = self.base_path / "tavern_characters"
        self.ui_test_path = self.base_path / "ui_test" 
        self.global_path = self.base_path / "global"
        
        # 确保目录结构存在
        self._ensure_directory_structure()
        
        # 加载映射和配置
        self.character_mapping = self._load_character_mapping()
        self.active_sessions = self._load_active_sessions()
        
        logger.info(f"TavernStorageManager initialized with base path: {self.base_path}")

    def _ensure_directory_structure(self):
        """确保所有必需的目录结构存在"""
        directories = [
            self.tavern_chars_path,
            self.ui_test_path / "test_character" / "current",
            self.ui_test_path / "temp",
            self.global_path
        ]
        
        for dir_path in directories:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        logger.debug("Storage directory structure ensured")

    def _load_character_mapping(self) -> Dict[str, str]:
        """加载角色ID映射"""
        mapping_file = self.global_path / "character_mapping.json"
        try:
            if mapping_file.exists():
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load character mapping: {e}")
        return {}

    def _save_character_mapping(self):
        """保存角色ID映射"""
        mapping_file = self.global_path / "character_mapping.json"
        try:
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(self.character_mapping, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save character mapping: {e}")

    def _load_active_sessions(self) -> Dict[str, Dict[str, Any]]:
        """加载活跃会话记录"""
        sessions_file = self.global_path / "active_sessions.json"
        try:
            if sessions_file.exists():
                with open(sessions_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load active sessions: {e}")
        return {}

    def _save_active_sessions(self):
        """保存活跃会话记录"""
        sessions_file = self.global_path / "active_sessions.json"
        try:
            with open(sessions_file, 'w', encoding='utf-8') as f:
                json.dump(self.active_sessions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save active sessions: {e}")

    def _sanitize_character_name(self, character_name: str) -> str:
        """将酒馆角色名转换为安全的目录名"""
        import re
        # 移除特殊字符，转为小写，用下划线连接
        sanitized = re.sub(r'[^\w\s-]', '', character_name.lower())
        sanitized = re.sub(r'[-\s]+', '_', sanitized)
        return sanitized.strip('_')

    def register_tavern_character(self, character_data: Dict[str, Any], session_id: str) -> str:
        """
        注册酒馆角色，创建对应的存储结构
        返回本地角色目录名
        """
        character_name = character_data.get('name', 'Unknown Character')
        character_id = character_data.get('character_id', character_name)  # 酒馆可能有ID
        
        # 生成本地目录名
        local_dir_name = self._sanitize_character_name(character_name)
        
        # 避免重名冲突
        base_dir_name = local_dir_name
        counter = 1
        while local_dir_name in self.character_mapping.values():
            local_dir_name = f"{base_dir_name}_{counter}"
            counter += 1
        
        # 创建角色目录结构
        char_path = self.tavern_chars_path / local_dir_name
        char_path.mkdir(exist_ok=True)
        (char_path / "sessions").mkdir(exist_ok=True)
        (char_path / "sessions" / "current").mkdir(exist_ok=True)
        
        # 保存角色卡信息副本
        character_file = char_path / "character_data.json"
        with open(character_file, 'w', encoding='utf-8') as f:
            json.dump(character_data, f, ensure_ascii=False, indent=2)
        
        # 创建元数据
        metadata = {
            "character_name": character_name,
            "character_id": character_id,
            "local_dir_name": local_dir_name,
            "created_at": datetime.now().isoformat(),
            "session_count": 1,
            "last_active": datetime.now().isoformat()
        }
        
        meta_file = char_path / "meta.json"
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        # 更新映射
        mapping_key = f"{character_id}_{character_name}" if character_id != character_name else character_name
        self.character_mapping[mapping_key] = local_dir_name
        self._save_character_mapping()
        
        # 记录活跃会话
        self.active_sessions[session_id] = {
            "character_mapping_key": mapping_key,
            "local_dir_name": local_dir_name,
            "character_name": character_name,
            "created_at": datetime.now().isoformat()
        }
        self._save_active_sessions()
        
        logger.info(f"Registered tavern character: {character_name} -> {local_dir_name}")
        return local_dir_name

    def get_character_storage_path(self, session_id: str, is_test: bool = False) -> Path:
        """
        获取角色的存储路径
        
        Args:
            session_id: 会话ID
            is_test: 是否是测试模式
        
        Returns:
            角色存储的完整路径
        """
        if is_test:
            return self.ui_test_path / "test_character" / "current"
        
        if session_id not in self.active_sessions:
            raise ValueError(f"Session {session_id} not found in active sessions")
        
        session_info = self.active_sessions[session_id]
        local_dir_name = session_info["local_dir_name"]
        
        return self.tavern_chars_path / local_dir_name / "sessions" / "current"

    def get_graph_file_path(self, session_id: str, is_test: bool = False) -> str:
        """获取知识图谱文件路径"""
        storage_path = self.get_character_storage_path(session_id, is_test)
        return str(storage_path / "knowledge_graph.graphml")

    def get_memory_file_path(self, session_id: str, is_test: bool = False) -> str:
        """获取记忆文件路径"""
        storage_path = self.get_character_storage_path(session_id, is_test)
        return str(storage_path / "conversation_memory.json")

    def create_new_session(self, character_mapping_key: str) -> str:
        """
        为已存在的角色创建新会话
        
        Args:
            character_mapping_key: 角色映射键
            
        Returns:
            新会话ID
        """
        if character_mapping_key not in self.character_mapping:
            raise ValueError(f"Character {character_mapping_key} not found")
        
        local_dir_name = self.character_mapping[character_mapping_key]
        char_path = self.tavern_chars_path / local_dir_name
        
        # 生成新会话ID和目录
        session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_session_id = f"{local_dir_name}_{session_timestamp}"
        
        # 备份当前会话到历史
        current_session_path = char_path / "sessions" / "current"
        if current_session_path.exists() and any(current_session_path.iterdir()):
            backup_path = char_path / "sessions" / session_timestamp
            shutil.copytree(current_session_path, backup_path)
            logger.info(f"Backed up session to {backup_path}")
            
            # 清空当前会话目录
            shutil.rmtree(current_session_path)
            current_session_path.mkdir()
        
        # 更新会话记录
        self.active_sessions[new_session_id] = {
            "character_mapping_key": character_mapping_key,
            "local_dir_name": local_dir_name,
            "character_name": self._get_character_name(character_mapping_key),
            "created_at": datetime.now().isoformat()
        }
        self._save_active_sessions()
        
        # 更新角色元数据
        self._update_character_metadata(local_dir_name)
        
        logger.info(f"Created new session: {new_session_id}")
        return new_session_id

    def clear_test_data(self):
        """清空UI测试数据"""
        try:
            test_path = self.ui_test_path / "test_character" / "current"
            if test_path.exists():
                shutil.rmtree(test_path)
                test_path.mkdir(parents=True)
            
            temp_path = self.ui_test_path / "temp"
            if temp_path.exists():
                shutil.rmtree(temp_path)
                temp_path.mkdir()
            
            logger.info("Test data cleared successfully")
        except Exception as e:
            logger.error(f"Failed to clear test data: {e}")

    def clear_character_data(self, character_mapping_key: str):
        """清空指定角色的所有数据"""
        if character_mapping_key not in self.character_mapping:
            logger.warning(f"Character {character_mapping_key} not found for clearing")
            return
        
        local_dir_name = self.character_mapping[character_mapping_key]
        char_path = self.tavern_chars_path / local_dir_name
        
        try:
            if char_path.exists():
                shutil.rmtree(char_path)
                logger.info(f"Cleared all data for character: {character_mapping_key}")
            
            # 从映射中移除
            del self.character_mapping[character_mapping_key]
            self._save_character_mapping()
            
            # 清理相关的活跃会话
            sessions_to_remove = [
                sid for sid, info in self.active_sessions.items() 
                if info.get("character_mapping_key") == character_mapping_key
            ]
            for sid in sessions_to_remove:
                del self.active_sessions[sid]
            self._save_active_sessions()
            
        except Exception as e:
            logger.error(f"Failed to clear character data: {e}")

    def list_characters(self) -> List[Dict[str, Any]]:
        """列出所有已注册的角色"""
        characters = []
        for mapping_key, local_dir_name in self.character_mapping.items():
            char_path = self.tavern_chars_path / local_dir_name
            meta_file = char_path / "meta.json"
            
            if meta_file.exists():
                try:
                    with open(meta_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        characters.append({
                            "mapping_key": mapping_key,
                            "local_dir": local_dir_name,
                            "character_name": metadata.get("character_name", "Unknown"),
                            "created_at": metadata.get("created_at"),
                            "session_count": metadata.get("session_count", 0),
                            "last_active": metadata.get("last_active")
                        })
                except Exception as e:
                    logger.warning(f"Failed to load metadata for {local_dir_name}: {e}")
        
        return characters

    def _get_character_name(self, character_mapping_key: str) -> str:
        """获取角色名称"""
        if character_mapping_key not in self.character_mapping:
            return "Unknown"
        
        local_dir_name = self.character_mapping[character_mapping_key]
        char_path = self.tavern_chars_path / local_dir_name
        meta_file = char_path / "meta.json"
        
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
                return metadata.get("character_name", "Unknown")
        except Exception:
            return character_mapping_key

    def _update_character_metadata(self, local_dir_name: str):
        """更新角色元数据"""
        char_path = self.tavern_chars_path / local_dir_name
        meta_file = char_path / "meta.json"
        
        try:
            metadata = {}
            if meta_file.exists():
                with open(meta_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            
            metadata["session_count"] = metadata.get("session_count", 0) + 1
            metadata["last_active"] = datetime.now().isoformat()
            
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to update metadata for {local_dir_name}: {e}")

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话信息"""
        return self.active_sessions.get(session_id)