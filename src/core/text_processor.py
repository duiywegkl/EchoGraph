"""
文本处理器 - 替代LLM客户端进行本地文本分析
专门为SillyTavern插件设计，不依赖外部LLM调用
"""
import re
import json
from typing import Dict, Any, List
from loguru import logger

class TextProcessor:
    """本地文本处理器（已停用）。图谱维护由LLM Agent独占。"""
    
    def __init__(self):
        self.entity_patterns = {}
        self.relation_patterns = []
        
    def extract_entities_and_relations(self, text: str) -> Dict[str, Any]:
        """
        从文本中提取实体和关系
        返回结构化数据，模拟LLM的JSON输出
        """
        logger.warning("TextProcessor 已停用：图谱维护仅允许LLM Agent。")
        return {"nodes_to_add": [], "edges_to_add": []}
    
    def extract_state_updates(self, text: str) -> Dict[str, Any]:
        """
        从LLM回复中提取状态更新
        这个方法会检测常见的状态变化模式
        """
        logger.warning("TextProcessor 已停用：图谱维护仅允许LLM Agent。")
        return {"nodes_to_update": [], "edges_to_add": []}
    
    def _generate_entity_id(self, name: str, entity_type: str) -> str:
        """生成实体ID，将中文名转换为英文ID"""
        # 简单的名称清理
        clean_name = re.sub(r'[^a-zA-Z\u4e00-\u9fa5]+', '_', name.lower())
        
        # 简单的中英文转换映射（可以扩展）
        translation_map = {
            "我": "player",
            "你": "you", 
            "主角": "protagonist",
            "商店": "shop",
            "酒馆": "tavern",
            "房间": "room",
            "剑": "sword",
            "盾牌": "shield"
        }
        
        if clean_name in translation_map:
            return translation_map[clean_name]
        
        # 如果没有映射，使用原名生成ID
        if entity_type != "unknown":
            return f"{entity_type}_{clean_name}"
        else:
            return clean_name
