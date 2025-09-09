import json
import re
from typing import Dict, Any, List, TYPE_CHECKING
from loguru import logger

from src.utils.config import config
from src.core.rpg_text_processor import RPGTextProcessor
from src.core.perception import PerceptionModule
from src.memory import GRAGMemory
from src.core.validation import ValidationLayer

if TYPE_CHECKING:
    from src.core.grag_update_agent import GRAGUpdateAgent

class GameEngine:
    """ChronoForge 核心游戏引擎，适配 SillyTavern 插件后端"""
    
    def __init__(self, memory: GRAGMemory, perception: PerceptionModule, rpg_processor: RPGTextProcessor, validation_layer: ValidationLayer, grag_agent: 'GRAGUpdateAgent' = None):
        self.memory = memory
        self.perception = perception
        self.rpg_processor = rpg_processor
        self.validation_layer = validation_layer
        self.grag_agent = grag_agent
        logger.info(f"GameEngine 初始化完成，{'支持智能Agent分析' if grag_agent else '使用本地文本处理器'}。")

    def initialize_from_tavern_data(self, character_card: Dict[str, Any], world_info: str):
        """
        使用本地文本处理器从角色卡和世界信息中解析实体和关系，初始化知识图谱。
        不再依赖外部LLM调用，使用内置的模式匹配。
        """
        logger.info("Initializing knowledge graph from Tavern data using local text processor...")
        
        try:
            # 1. 准备要分析的文本
            char_description = character_card.get('description', '')
            char_name = character_card.get('name', 'Unknown Character')
            char_personality = character_card.get('personality', '')
            char_scenario = character_card.get('scenario', '')
            
            # 合并所有文本
            combined_text = f"""
            角色名: {char_name}
            描述: {char_description}
            性格: {char_personality}
            场景: {char_scenario}
            世界信息: {world_info}
            """.strip()
            
            logger.info(f"分析文本长度: {len(combined_text)} 字符")
            
            # 2. 使用RPG文本处理器提取实体和关系
            extracted_data = self.rpg_processor.extract_rpg_entities_and_relations(combined_text)
            
            # 3. 添加角色本身作为主要实体
            character_id = self.rpg_processor._generate_rpg_entity_id(char_name, "character")
            main_character = {
                "node_id": character_id,
                "type": "character",
                "attributes": {
                    "name": char_name,
                    "description": char_description[:200] if char_description else "主要角色",
                    "personality": char_personality[:100] if char_personality else "",
                    "is_main_character": True,
                    "source": "character_card"
                }
            }
            extracted_data["nodes_to_add"].insert(0, main_character)
            
            # 4. 应用提取出的数据来更新知识图谱
            nodes = extracted_data.get("nodes_to_add", [])
            edges = extracted_data.get("edges_to_add", [])
            
            nodes_added = 0
            edges_added = 0
            
            for node_data in nodes:
                try:
                    self.memory.add_or_update_node(
                        node_data['node_id'], 
                        node_data['type'], 
                        **node_data.get('attributes', {})
                    )
                    nodes_added += 1
                except Exception as e:
                    logger.warning(f"Failed to add node {node_data.get('node_id', 'unknown')}: {e}")
            
            for edge_data in edges:
                try:
                    self.memory.add_edge(
                        edge_data['source'], 
                        edge_data['target'], 
                        edge_data['relationship']
                    )
                    edges_added += 1
                except Exception as e:
                    logger.warning(f"Failed to add edge {edge_data.get('source', '')} -> {edge_data.get('target', '')}: {e}")
            
            logger.info(f"Successfully initialized graph: {nodes_added} nodes, {edges_added} edges added.")
            
            # 保存知识图谱
            if self.memory.graph_save_path:
                self.memory.knowledge_graph.save_graph(self.memory.graph_save_path)
            
            return {
                "nodes_added": nodes_added,
                "edges_added": edges_added,
                "character_name": char_name
            }

        except Exception as e:
            logger.error(f"Failed to initialize from tavern data: {e}")
            # 即使失败，也要确保有一个基础的角色节点
            fallback_char = character_card.get('name', 'Unknown Character')
            fallback_id = f"character_{fallback_char.lower().replace(' ', '_')}"
            
            try:
                self.memory.add_or_update_node(
                    fallback_id,
                    "character",
                    name=fallback_char,
                    description="Fallback character node",
                    is_main_character=True
                )
                logger.info(f"Created fallback character node: {fallback_id}")
                return {"nodes_added": 1, "edges_added": 0, "character_name": fallback_char}
            except Exception as fallback_error:
                logger.error(f"Even fallback initialization failed: {fallback_error}")
                raise ValueError("Complete initialization failure.")

    def extract_updates_from_response(self, llm_response: str, user_input: str = "") -> Dict[str, Any]:
        """
        智能分析对话内容，生成精确的知识图谱更新操作。
        优先使用GRAG Agent进行分析，回退到本地处理器。
        """
        if self.grag_agent:
            logger.info("使用GRAG智能Agent分析对话更新...")
            return self._extract_with_agent(user_input, llm_response)
        else:
            logger.info("使用本地文本处理器提取更新...")
            return self._extract_with_local_processor(llm_response)
    
    def _extract_with_agent(self, user_input: str, llm_response: str) -> Dict[str, Any]:
        """使用GRAG Agent进行智能分析"""
        try:
            # 1. Agent分析对话生成更新指令
            recent_context = self._get_recent_conversation_context()
            analysis_result = self.grag_agent.analyze_conversation_for_updates(
                user_input=user_input,
                llm_response=llm_response, 
                current_graph=self.memory.knowledge_graph,
                recent_context=recent_context
            )
            
            if "error" in analysis_result:
                logger.warning(f"Agent分析失败，回退到本地处理器: {analysis_result['error']}")
                return self._extract_with_local_processor(llm_response)
            
            # 2. 将Agent结果转换为执行格式
            execution_format = self.grag_agent.convert_to_execution_format(analysis_result)
            
            # 3. 验证更新
            validated_updates = self.validation_layer.validate(execution_format, self.memory.knowledge_graph)
            
            # 4. 应用更新
            return self._apply_validated_updates(validated_updates, source="grag_agent")
            
        except Exception as e:
            logger.error(f"Agent分析过程出错: {e}")
            logger.info("回退到本地文本处理器...")
            return self._extract_with_local_processor(llm_response)
    
    def _extract_with_local_processor(self, llm_response: str) -> Dict[str, Any]:
        """使用本地RPG文本处理器（回退方案）"""
        try:
            # 使用RPG文本处理器提取完整的游戏元素更新
            updates = self.rpg_processor.extract_rpg_entities_and_relations(llm_response)
            
            # 验证并应用更新
            validated_updates = self.validation_layer.validate(updates, self.memory.knowledge_graph)

            # 应用更新
            return self._apply_validated_updates(validated_updates, source="local_processor")
            
        except Exception as e:
            logger.error(f"本地处理器分析失败: {e}")
            # 返回安全的空结果
            return {"nodes_updated": 0, "edges_added": 0, "nodes_deleted": 0, "edges_deleted": 0}
    
    def _apply_validated_updates(self, validated_updates: Dict[str, Any], source: str = "unknown") -> Dict[str, Any]:
        """统一的更新应用逻辑"""
        if not validated_updates:
            logger.info("没有有效的更新需要应用")
            return {"nodes_updated": 0, "edges_added": 0, "nodes_deleted": 0, "edges_deleted": 0}

        nodes_updated_count = len(validated_updates.get("nodes_to_update", []))
        edges_added_count = len(validated_updates.get("edges_to_add", []))
        nodes_deleted_count = 0
        edges_deleted_count = 0

        # 处理删除事件（优先）
        deletion_stats = self._process_deletion_events(validated_updates)
        nodes_deleted_count = deletion_stats.get("nodes_deleted", 0)
        edges_deleted_count = deletion_stats.get("edges_deleted", 0)

        # 应用节点更新
        for node_update in validated_updates.get("nodes_to_update", []):
            try:
                # 检查节点是否存在，如果不存在则创建
                if not self.memory.knowledge_graph.graph.has_node(node_update['node_id']):
                    # 尝试从属性中推断类型
                    node_type = node_update.get('type', 'unknown')
                    if node_type == 'unknown' and "location" in node_update.get('attributes', {}):
                        node_type = "character" # 有位置的通常是角色
                    
                    self.memory.add_or_update_node(
                        node_update['node_id'], 
                        node_type, 
                        **node_update['attributes']
                    )
                else:
                    # 节点存在，只更新属性
                    existing_node = self.memory.knowledge_graph.get_node(node_update['node_id'])
                    node_type = existing_node.get('type', 'unknown')
                    self.memory.add_or_update_node(
                        node_update['node_id'], 
                        node_type, 
                        **node_update['attributes']
                    )
            except Exception as e:
                logger.warning(f"Failed to update node {node_update['node_id']}: {e}")
                nodes_updated_count -= 1
        
        # 应用边更新
        for edge_add in validated_updates.get("edges_to_add", []):
            try:
                self.memory.add_edge(
                    edge_add['source'], 
                    edge_add['target'], 
                    edge_add['relationship']
                )
            except Exception as e:
                logger.warning(f"Failed to add edge {edge_add['source']} -> {edge_add['target']}: {e}")
                edges_added_count -= 1
        
        logger.info(f"成功应用更新({source}): {nodes_updated_count} nodes updated, {edges_added_count} edges added, {nodes_deleted_count} nodes deleted, {edges_deleted_count} edges deleted.")
        
        # 保存知识图谱
        if self.memory.graph_save_path:
            self.memory.knowledge_graph.save_graph(self.memory.graph_save_path)
        
        return {
            "nodes_updated": nodes_updated_count, 
            "edges_added": edges_added_count,
            "nodes_deleted": nodes_deleted_count,
            "edges_deleted": edges_deleted_count
        }
    
    def _get_recent_conversation_context(self) -> str:
        """获取最近的对话上下文用于Agent分析"""
        try:
            recent_history = self.memory.basic_memory.conversation_history[-3:]  # 最近3轮对话
            context_parts = []
            
            for turn in recent_history:
                user_msg = turn.get("user", "")
                assistant_msg = turn.get("assistant", "")
                if user_msg:
                    context_parts.append(f"用户: {user_msg}")
                if assistant_msg:
                    context_parts.append(f"助手: {assistant_msg}")
            
            return "\n".join(context_parts) if context_parts else ""
        except:
            return ""

    def _process_deletion_events(self, validated_updates: Dict[str, Any]) -> Dict[str, int]:
        """
        处理删除事件，包括节点删除和边删除
        
        Args:
            validated_updates: 验证后的更新数据
            
        Returns:
            Dict: 删除统计信息
        """
        nodes_deleted = 0
        edges_deleted = 0
        
        # 处理节点删除
        for node_deletion in validated_updates.get("nodes_to_delete", []):
            try:
                node_id = node_deletion["node_id"]
                deletion_type = node_deletion.get("deletion_type", "default")
                reason = node_deletion.get("reason", "No reason provided")
                
                if deletion_type == "death":
                    # 角色死亡使用软删除
                    self.memory.mark_node_as_deleted(node_id, reason)
                    logger.info(f"Character marked as dead: {node_id} - {reason}")
                elif deletion_type == "lost":
                    # 物品丢失使用硬删除
                    if self.memory.delete_node(node_id):
                        logger.info(f"Item permanently deleted: {node_id} - {reason}")
                    else:
                        logger.warning(f"Failed to delete node {node_id}: node not found")
                        continue
                else:
                    # 默认软删除
                    self.memory.mark_node_as_deleted(node_id, reason)
                    logger.info(f"Node marked as deleted: {node_id} - {reason}")
                
                nodes_deleted += 1
                
            except Exception as e:
                logger.warning(f"Failed to process node deletion {node_deletion.get('node_id', 'unknown')}: {e}")
        
        # 处理边删除
        for edge_deletion in validated_updates.get("edges_to_delete", []):
            try:
                source = edge_deletion.get("source")
                target = edge_deletion.get("target") 
                relationship = edge_deletion.get("relationship")
                reason = edge_deletion.get("reason", "No reason provided")
                
                # 支持通配符删除
                if source == "*" or relationship == "*":
                    # 找到所有匹配的边并删除
                    graph = self.memory.knowledge_graph.graph
                    edges_to_remove = []
                    
                    for src, tgt, edge_data in graph.edges(data=True):
                        match = True
                        if source != "*" and src != source:
                            match = False
                        if target != "*" and tgt != target:
                            match = False
                        if relationship != "*" and edge_data.get("relationship") != relationship:
                            match = False
                        
                        if match:
                            edges_to_remove.append((src, tgt, edge_data.get("relationship")))
                    
                    for src, tgt, rel in edges_to_remove:
                        if self.memory.delete_edge(src, tgt, rel):
                            edges_deleted += 1
                            logger.info(f"Edge deleted: {src} --{rel}--> {tgt} - {reason}")
                else:
                    # 精确删除
                    if self.memory.delete_edge(source, target, relationship):
                        edges_deleted += 1
                        logger.info(f"Edge deleted: {source} --{relationship}--> {target} - {reason}")
                    else:
                        logger.warning(f"Failed to delete edge {source} -> {target}: edge not found")
                        
            except Exception as e:
                logger.warning(f"Failed to process edge deletion: {e}")
        
        return {
            "nodes_deleted": nodes_deleted,
            "edges_deleted": edges_deleted
        }
