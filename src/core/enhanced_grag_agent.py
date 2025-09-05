#!/usr/bin/env python3
"""
增强的GRAG Agent - 支持基于世界观的完整节点创建
"""

from typing import Dict, Any, List, Optional
from loguru import logger
import json

from .grag_update_agent import GRAGUpdateAgent
from src.core.llm_client import LLMClient
from src.graph.knowledge_graph import KnowledgeGraph


class EnhancedGRAGAgent(GRAGUpdateAgent):
    """
    增强版GRAG Agent，支持：
    1. 基于世界观的完整节点创建
    2. 智能属性推断
    3. 确保节点完整性
    """
    
    def __init__(self, llm_client: LLMClient):
        super().__init__(llm_client)
        self.world_context = self._build_world_context()
        
    def _build_world_context(self) -> Dict[str, Any]:
        """构建世界观上下文"""
        return {
            "races": {
                "elf": {
                    "default_attributes": {
                        "lifespan": "long", "magic_affinity": "high", 
                        "nature_connection": "strong", "agility": "high"
                    }
                },
                "human": {
                    "default_attributes": {
                        "lifespan": "medium", "adaptability": "high",
                        "learning_rate": "fast", "versatility": "high"
                    }
                },
                "dwarf": {
                    "default_attributes": {
                        "lifespan": "long", "craftsmanship": "master",
                        "strength": "high", "magic_resistance": "high"
                    }
                }
            },
            "professions": {
                "warrior": {
                    "default_attributes": {
                        "combat_skill": "high", "leadership": "medium",
                        "equipment": ["sword", "shield", "armor"]
                    }
                },
                "mage": {
                    "default_attributes": {
                        "magic_power": "high", "knowledge": "extensive",
                        "equipment": ["staff", "spellbook", "robes"]
                    }
                }
            },
            "item_categories": {
                "weapon": {
                    "default_attributes": {
                        "durability": "medium", "requires_maintenance": True
                    }
                },
                "magic_item": {
                    "default_attributes": {
                        "magical_energy": "present", "requires_attunement": True
                    }
                }
            },
            "locations": {
                "forest": {
                    "default_attributes": {
                        "climate": "temperate", "wildlife": "abundant",
                        "visibility": "limited", "natural_resources": ["wood", "herbs"]
                    }
                },
                "city": {
                    "default_attributes": {
                        "population": "high", "services": "comprehensive",
                        "safety": "high", "trade": "active"
                    }
                }
            }
        }
    
    def analyze_conversation_for_updates(
        self, 
        user_input: str, 
        llm_response: str, 
        current_graph: KnowledgeGraph,
        recent_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        增强版对话分析，确保完整节点创建
        """
        try:
            # 使用增强prompt进行分析
            analysis_result = super().analyze_conversation_for_updates(
                user_input, llm_response, current_graph, recent_context
            )
            
            if "error" in analysis_result:
                return analysis_result
            
            # 增强操作：确保节点完整性
            enhanced_operations = self._enhance_operations(
                analysis_result.get("operations", []),
                current_graph
            )
            
            analysis_result["operations"] = enhanced_operations
            analysis_result["enhanced"] = True
            
            logger.info(f"增强分析完成: {len(enhanced_operations)} 个增强操作")
            return analysis_result
            
        except Exception as e:
            logger.error(f"增强GRAG分析失败: {e}")
            return {"operations": [], "error": str(e)}
    
    def _enhance_operations(
        self, 
        operations: List[Dict[str, Any]], 
        current_graph: KnowledgeGraph
    ) -> List[Dict[str, Any]]:
        """
        增强操作列表，确保节点完整性
        """
        enhanced_ops = []
        node_creation_queue = {}
        edge_queue = []
        
        # 第一轮：处理节点创建和更新，收集边创建请求
        for op in operations:
            if op.get("type") == "add_node":
                # 增强节点创建
                enhanced_node = self._enhance_node_creation(op)
                enhanced_ops.append(enhanced_node)
                node_creation_queue[op["node_id"]] = enhanced_node
                
            elif op.get("type") == "add_edge":
                # 延迟边处理，确保节点存在
                edge_queue.append(op)
                
            else:
                # 其他操作直接添加
                enhanced_ops.append(op)
        
        # 第二轮：处理边创建，如果目标节点不存在则创建
        for edge_op in edge_queue:
            missing_nodes = self._check_missing_nodes_for_edge(
                edge_op, current_graph, node_creation_queue
            )
            
            # 为缺失的节点创建占位符节点
            for node_id, node_info in missing_nodes.items():
                placeholder_node = self._create_placeholder_node(node_id, node_info)
                enhanced_ops.append(placeholder_node)
                node_creation_queue[node_id] = placeholder_node
                logger.info(f"为边关系创建占位符节点: {node_id}")
            
            # 添加边操作
            enhanced_ops.append(edge_op)
        
        return enhanced_ops
    
    def _enhance_node_creation(self, node_op: Dict[str, Any]) -> Dict[str, Any]:
        """
        增强节点创建，添加基于世界观的完整属性
        """
        enhanced_op = node_op.copy()
        node_type = node_op.get("node_type", "unknown")
        attributes = node_op.get("attributes", {})
        
        # 基于节点类型添加默认属性
        if node_type == "character":
            enhanced_attributes = self._enhance_character_attributes(attributes)
        elif node_type == "item":
            enhanced_attributes = self._enhance_item_attributes(attributes)
        elif node_type == "location":
            enhanced_attributes = self._enhance_location_attributes(attributes)
        elif node_type == "event":
            enhanced_attributes = self._enhance_event_attributes(attributes)
        else:
            enhanced_attributes = self._enhance_generic_attributes(attributes)
        
        enhanced_op["attributes"] = enhanced_attributes
        enhanced_op["enhanced"] = True
        
        logger.debug(f"增强节点 {node_op['node_id']}: 添加了 {len(enhanced_attributes) - len(attributes)} 个属性")
        return enhanced_op
    
    def _enhance_character_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """增强角色节点属性"""
        enhanced = attributes.copy()
        
        # 必备基础属性
        if "name" not in enhanced:
            enhanced["name"] = enhanced.get("node_id", "Unknown Character")
        if "type" not in enhanced:
            enhanced["type"] = "character"
        if "description" not in enhanced:
            enhanced["description"] = f"A character named {enhanced.get('name', 'Unknown')}"
        
        # 根据种族添加属性
        race = enhanced.get("race", "").lower()
        if race and race in self.world_context["races"]:
            race_defaults = self.world_context["races"][race]["default_attributes"]
            for key, value in race_defaults.items():
                if key not in enhanced:
                    enhanced[key] = value
        
        # 根据职业添加属性
        profession = enhanced.get("profession", "").lower()
        if profession and profession in self.world_context["professions"]:
            prof_defaults = self.world_context["professions"][profession]["default_attributes"]
            for key, value in prof_defaults.items():
                if key not in enhanced:
                    enhanced[key] = value
        
        # 默认状态属性
        if "health" not in enhanced:
            enhanced["health"] = enhanced.get("max_health", 100)
        if "location" not in enhanced:
            enhanced["location"] = "unknown"
        if "disposition" not in enhanced:
            enhanced["disposition"] = "neutral"
        if "threat_level" not in enhanced:
            enhanced["threat_level"] = "unknown"
        
        return enhanced
    
    def _enhance_item_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """增强物品节点属性"""
        enhanced = attributes.copy()
        
        # 必备基础属性
        if "name" not in enhanced:
            enhanced["name"] = enhanced.get("node_id", "Unknown Item")
        if "type" not in enhanced:
            enhanced["type"] = "item"
        if "category" not in enhanced:
            enhanced["category"] = "misc"
        if "description" not in enhanced:
            enhanced["description"] = f"An item called {enhanced.get('name', 'Unknown')}"
        
        # 根据分类添加属性
        category = enhanced.get("category", "").lower()
        if category and category in self.world_context["item_categories"]:
            cat_defaults = self.world_context["item_categories"][category]["default_attributes"]
            for key, value in cat_defaults.items():
                if key not in enhanced:
                    enhanced[key] = value
        
        # 默认物品属性
        if "rarity" not in enhanced:
            enhanced["rarity"] = "common"
        if "durability" not in enhanced:
            enhanced["durability"] = "good"
        if "value" not in enhanced:
            enhanced["value"] = "unknown"
        
        return enhanced
    
    def _enhance_location_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """增强地点节点属性"""
        enhanced = attributes.copy()
        
        # 必备基础属性
        if "name" not in enhanced:
            enhanced["name"] = enhanced.get("node_id", "Unknown Location")
        if "type" not in enhanced:
            enhanced["type"] = "location"
        if "description" not in enhanced:
            enhanced["description"] = f"A location called {enhanced.get('name', 'Unknown')}"
        
        # 根据地点类型添加属性
        location_type = enhanced.get("location_type", "").lower()
        if location_type and location_type in self.world_context["locations"]:
            loc_defaults = self.world_context["locations"][location_type]["default_attributes"]
            for key, value in loc_defaults.items():
                if key not in enhanced:
                    enhanced[key] = value
        
        # 默认地点属性
        if "safety_level" not in enhanced:
            enhanced["safety_level"] = "unknown"
        if "accessibility" not in enhanced:
            enhanced["accessibility"] = "unknown"
        
        return enhanced
    
    def _enhance_event_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """增强事件节点属性"""
        enhanced = attributes.copy()
        
        # 必备基础属性
        if "name" not in enhanced:
            enhanced["name"] = enhanced.get("node_id", "Unknown Event")
        if "type" not in enhanced:
            enhanced["type"] = "event"
        if "timestamp" not in enhanced:
            enhanced["timestamp"] = "recent"
        if "description" not in enhanced:
            enhanced["description"] = f"An event called {enhanced.get('name', 'Unknown')}"
        
        # 默认事件属性
        if "outcome" not in enhanced:
            enhanced["outcome"] = "ongoing"
        if "importance" not in enhanced:
            enhanced["importance"] = "medium"
        
        return enhanced
    
    def _enhance_generic_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """增强通用节点属性"""
        enhanced = attributes.copy()
        
        # 通用必备属性
        if "name" not in enhanced:
            enhanced["name"] = enhanced.get("node_id", "Unknown Entity")
        if "type" not in enhanced:
            enhanced["type"] = "unknown"
        if "description" not in enhanced:
            enhanced["description"] = f"An entity called {enhanced.get('name', 'Unknown')}"
        
        return enhanced
    
    def _check_missing_nodes_for_edge(
        self, 
        edge_op: Dict[str, Any], 
        current_graph: KnowledgeGraph,
        node_creation_queue: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        检查边操作中缺失的节点
        """
        missing_nodes = {}
        source = edge_op.get("source")
        target = edge_op.get("target")
        
        # 检查源节点
        if source and not self._node_exists_or_will_be_created(
            source, current_graph, node_creation_queue
        ):
            missing_nodes[source] = {
                "inferred_from": "edge_source",
                "relationship": edge_op.get("relationship", "unknown")
            }
        
        # 检查目标节点
        if target and not self._node_exists_or_will_be_created(
            target, current_graph, node_creation_queue
        ):
            missing_nodes[target] = {
                "inferred_from": "edge_target",
                "relationship": edge_op.get("relationship", "unknown")
            }
        
        return missing_nodes
    
    def _node_exists_or_will_be_created(
        self, 
        node_id: str, 
        current_graph: KnowledgeGraph,
        node_creation_queue: Dict[str, Dict[str, Any]]
    ) -> bool:
        """
        检查节点是否存在或将要被创建
        """
        return (
            current_graph.graph.has_node(node_id) or 
            node_id in node_creation_queue
        )
    
    def _create_placeholder_node(self, node_id: str, node_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        为缺失的节点创建占位符
        """
        # 尝试从节点ID推断类型和属性
        inferred_type = self._infer_node_type_from_id(node_id)
        inferred_name = self._infer_node_name_from_id(node_id)
        
        placeholder = {
            "type": "add_node",
            "node_id": node_id,
            "node_type": inferred_type,
            "attributes": {
                "name": inferred_name,
                "type": inferred_type,
                "description": f"Auto-created node for {inferred_name}",
                "auto_generated": True,
                "creation_reason": f"Required for relationship: {node_info.get('relationship', 'unknown')}"
            },
            "reason": f"Auto-generated placeholder for missing node in edge relationship"
        }
        
        # 基于推断的类型添加默认属性
        if inferred_type == "character":
            placeholder["attributes"].update({
                "race": "unknown",
                "location": "unknown",
                "disposition": "unknown"
            })
        elif inferred_type == "item":
            placeholder["attributes"].update({
                "category": "misc",
                "rarity": "unknown"
            })
        elif inferred_type == "location":
            placeholder["attributes"].update({
                "safety_level": "unknown",
                "location_type": "unknown"
            })
        
        return placeholder
    
    def _infer_node_type_from_id(self, node_id: str) -> str:
        """从节点ID推断节点类型"""
        node_id_lower = node_id.lower()
        
        # 常见角色关键词
        if any(keyword in node_id_lower for keyword in [
            "character", "npc", "player", "hero", "villain", "elf", "human", "dwarf"
        ]):
            return "character"
        
        # 常见物品关键词
        if any(keyword in node_id_lower for keyword in [
            "sword", "weapon", "armor", "potion", "item", "equipment", "tool"
        ]):
            return "item"
        
        # 常见地点关键词
        if any(keyword in node_id_lower for keyword in [
            "forest", "city", "castle", "dungeon", "location", "place", "room"
        ]):
            return "location"
        
        # 默认为未知
        return "unknown"
    
    def _infer_node_name_from_id(self, node_id: str) -> str:
        """从节点ID推断显示名称"""
        # 移除常见前缀
        name = node_id
        for prefix in ["character_", "item_", "location_", "npc_", "player_"]:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        
        # 替换下划线为空格并首字母大写
        name = name.replace("_", " ").title()
        
        return name if name else node_id