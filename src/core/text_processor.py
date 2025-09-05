"""
文本处理器 - 替代LLM客户端进行本地文本分析
专门为SillyTavern插件设计，不依赖外部LLM调用
"""
import re
import json
from typing import Dict, Any, List
from loguru import logger

class TextProcessor:
    """本地文本处理器，用于替代LLM进行简单的信息提取"""
    
    def __init__(self):
        # 基础实体识别模式
        self.entity_patterns = {
            "character": [
                r"(我|你|他|她|它)(?:是|叫|名字叫|被称为)([^，。！？\s]+)",
                r"([A-Za-z\u4e00-\u9fa5]+)(?:是一个|是个)(?:角色|人物|角色扮演|character)",
            ],
            "location": [
                r"(?:在|到|前往|去|来到)([^，。！？\s]+)(?:地方|位置|房间|城市|村庄)",
                r"([A-Za-z\u4e00-\u9fa5]+)(?:是一个|是个)(?:地点|地方|位置|房间|城市|村庄)",
            ],
            "item": [
                r"(?:拿到|获得|捡起|使用|装备)([^，。！？\s]+)(?:物品|道具|装备|武器|工具)",
                r"([A-Za-z\u4e00-\u9fa5]+)(?:是一个|是个)(?:物品|道具|装备|武器|工具)",
            ],
        }
        
        # 关系识别模式
        self.relation_patterns = [
            (r"([^，。！？\s]+)(?:属于|归属于|是)([^，。！？\s]+)的", "belongs_to"),
            (r"([^，。！？\s]+)(?:位于|在)([^，。！？\s]+)", "located_in"),
            (r"([^，。！？\s]+)(?:持有|拥有|带着)([^，。！？\s]+)", "owns"),
            (r"([^，。！？\s]+)(?:认识|知道|见过)([^，。！？\s]+)", "knows"),
        ]
        
    def extract_entities_and_relations(self, text: str) -> Dict[str, Any]:
        """
        从文本中提取实体和关系
        返回结构化数据，模拟LLM的JSON输出
        """
        nodes_to_add = []
        edges_to_add = []
        
        # 1. 提取实体
        for entity_type, patterns in self.entity_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    if len(match.groups()) >= 2:
                        entity_name = match.group(2).strip()
                    else:
                        entity_name = match.group(1).strip()
                    
                    if entity_name and len(entity_name) > 1:
                        # 生成英文ID
                        entity_id = self._generate_entity_id(entity_name, entity_type)
                        nodes_to_add.append({
                            "node_id": entity_id,
                            "type": entity_type,
                            "attributes": {
                                "name": entity_name,
                                "description": f"从文本中提取的{entity_type}",
                                "source": "text_extraction"
                            }
                        })
        
        # 2. 提取关系
        for pattern, relation_type in self.relation_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 2:
                    source_name = match.group(1).strip()
                    target_name = match.group(2).strip()
                    
                    if source_name and target_name:
                        source_id = self._generate_entity_id(source_name, "unknown")
                        target_id = self._generate_entity_id(target_name, "unknown")
                        
                        edges_to_add.append({
                            "source": source_id,
                            "target": target_id,
                            "relationship": relation_type
                        })
        
        result = {
            "nodes_to_add": nodes_to_add,
            "edges_to_add": edges_to_add
        }
        
        logger.info(f"文本处理完成: 提取了 {len(nodes_to_add)} 个实体, {len(edges_to_add)} 个关系")
        return result
    
    def extract_state_updates(self, text: str) -> Dict[str, Any]:
        """
        从LLM回复中提取状态更新
        这个方法会检测常见的状态变化模式
        """
        nodes_to_update = []
        edges_to_add = []
        
        # 状态变化模式
        state_patterns = [
            (r"([^，。！？\s]+)(?:的)?(?:位置|地点)(?:变成了|变为|是)([^，。！？\s]+)", "location"),
            (r"([^，。！？\s]+)(?:的)?(?:状态|情况)(?:变成了|变为|是)([^，。！？\s]+)", "status"),
            (r"([^，。！？\s]+)(?:的)?(?:血量|生命|HP)(?:变成了|变为|是)([^，。！？\s]+)", "health"),
            (r"([^，。！？\s]+)(?:现在|目前)(?:在|位于)([^，。！？\s]+)", "location"),
        ]
        
        for pattern, attribute in state_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 2:
                    entity_name = match.group(1).strip()
                    new_value = match.group(2).strip()
                    
                    if entity_name and new_value:
                        entity_id = self._generate_entity_id(entity_name, "unknown")
                        nodes_to_update.append({
                            "node_id": entity_id,
                            "attributes": {attribute: new_value}
                        })
        
        result = {
            "nodes_to_update": nodes_to_update,
            "edges_to_add": edges_to_add
        }
        
        logger.info(f"状态更新提取完成: {len(nodes_to_update)} 个节点更新")
        return result
    
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