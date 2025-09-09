from collections import deque
from typing import List, Dict, Any, Optional
from loguru import logger

from src.memory.basic_memory import BasicMemory
from src.graph.knowledge_graph import KnowledgeGraph

class GRAGMemory:
    """
    GRAG三层记忆系统，整合了热、温、冷三种记忆。
    - 热记忆 (Hot Memory): 最近的对话历史，使用 BasicMemory 的 deque。
    - 温记忆 (Warm Memory): 关键状态键值对，使用 BasicMemory 的 state_table。
    - 冷记忆 (Cold Memory): 结构化的知识图谱，使用 KnowledgeGraph。
    """

    def __init__(self, hot_memory_size: int = 10, graph_save_path: Optional[str] = None):
        """
        初始化三层记忆系统。

        Args:
            hot_memory_size (int): 热记忆要保留的最近对话轮数。
            graph_save_path (Optional[str]): 知识图谱的保存/加载路径。
        """
        # 热、温记忆层 (继承自BasicMemory的功能)
        self.basic_memory = BasicMemory(max_size=hot_memory_size)
        
        # 冷记忆层
        self.knowledge_graph = KnowledgeGraph()
        self.graph_save_path = graph_save_path
        if self.graph_save_path:
            self.knowledge_graph.load_graph(self.graph_save_path)

        # 加载UI中的实体数据到知识图谱
        self._load_entities_from_json()

        # 数据变化追踪
        self._data_changed = False
        self._last_conversation_count = 0

        logger.info("GRAGMemory initialized with Hot, Warm, and Cold memory layers.")

    def _load_entities_from_json(self):
        """从UI的entities.json文件加载实体到知识图谱中"""
        import json
        import os
        from pathlib import Path
        
        # 实体文件路径
        entities_file = Path(__file__).parent.parent.parent / "data" / "entities.json"
        
        if not entities_file.exists():
            logger.info(f"实体文件 {entities_file} 不存在，跳过加载")
            return
        
        try:
            with open(entities_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            entities = data.get('entities', [])
            if not entities:
                logger.info("实体文件中没有实体数据")
                return
            
            entities_loaded = 0
            for entity in entities:
                entity_name = entity.get('name')
                entity_type = entity.get('type', 'concept')
                
                if not entity_name:
                    logger.warning(f"跳过没有名称的实体: {entity}")
                    continue
                
                # 准备属性
                attributes = {}
                if entity.get('description'):
                    attributes['description'] = entity['description']
                if entity.get('created_time'):
                    attributes['created_time'] = entity['created_time']
                if entity.get('last_modified'):
                    attributes['last_modified'] = entity['last_modified']
                
                # 添加动态属性
                if entity.get('attributes'):
                    for key, value in entity['attributes'].items():
                        attributes[key] = value
                
                # 将实体添加到知识图谱
                self.knowledge_graph.add_or_update_node(entity_name, entity_type, **attributes)
                entities_loaded += 1
            
            logger.info(f"✅ 成功从 entities.json 加载了 {entities_loaded} 个实体到知识图谱")
            
            # 加载关系
            relationships = data.get('relationships', [])
            relationships_loaded = 0
            
            for rel in relationships:
                try:
                    source = rel.get('source')
                    target = rel.get('target')
                    relationship_type = rel.get('relationship', 'related_to')
                    description = rel.get('description', '')
                    
                    if source and target:
                        # 检查源节点和目标节点是否存在
                        if (self.knowledge_graph.graph.has_node(source) and 
                            self.knowledge_graph.graph.has_node(target)):
                            
                            # 添加关系属性
                            rel_attrs = {'relationship': relationship_type}
                            if description:
                                rel_attrs['description'] = description
                            
                            # 添加其他属性
                            if rel.get('attributes'):
                                rel_attrs.update(rel['attributes'])
                            
                            # 添加边到知识图谱
                            self.knowledge_graph.graph.add_edge(source, target, **rel_attrs)
                            relationships_loaded += 1
                            
                        else:
                            logger.warning(f"跳过关系 {source} -> {target}：节点不存在")
                    else:
                        logger.warning(f"跳过无效关系: {rel}")
                        
                except Exception as e:
                    logger.warning(f"加载关系失败 {rel}: {e}")
            
            logger.info(f"✅ 成功从 entities.json 加载了 {relationships_loaded} 个关系到知识图谱")
            
        except Exception as e:
            logger.error(f"❌ 从 entities.json 加载实体失败: {e}")
            logger.exception("详细错误信息:")
    
    def sync_entities_to_json(self):
        """将知识图谱中的实体同步到entities.json文件"""
        import json
        import time
        from pathlib import Path
        
        # 实体文件路径
        entities_file = Path(__file__).parent.parent.parent / "data" / "entities.json"
        entities_file.parent.mkdir(exist_ok=True, parents=True)
        
        try:
            entities = []
            
            # 从知识图谱中获取所有节点
            for node_id, attrs in self.knowledge_graph.graph.nodes(data=True):
                entity = {
                    'name': node_id,
                    'type': attrs.get('type', 'concept'),
                    'description': attrs.get('description', ''),
                    'created_time': attrs.get('created_time', time.time()),
                    'last_modified': attrs.get('last_modified', time.time()),
                    'attributes': {}
                }
                
                # 添加动态属性，排除系统属性
                excluded_keys = {'type', 'description', 'created_time', 'last_modified'}
                for key, value in attrs.items():
                    if key not in excluded_keys:
                        entity['attributes'][key] = value
                
                entities.append(entity)
            
            # 获取所有关系
            relationships = []
            for source, target, attrs in self.knowledge_graph.graph.edges(data=True):
                relationship = {
                    'source': source,
                    'target': target,
                    'relationship': attrs.get('relationship', 'related_to'),
                    'description': attrs.get('description', ''),
                    'attributes': {k: v for k, v in attrs.items() if k not in ['relationship', 'description']}
                }
                relationships.append(relationship)
            
            # 保存到文件
            data = {
                'entities': entities,
                'relationships': relationships,  # 新增：保存关系
                'last_modified': time.time()
            }
            
            with open(entities_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ 成功同步 {len(entities)} 个实体和 {len(relationships)} 个关系到 entities.json")
            
        except Exception as e:
            logger.error(f"❌ 同步实体到 entities.json 失败: {e}")
            logger.exception("详细错误信息:")

    def reload_entities_from_json(self):
        """重新加载entities.json文件中的实体"""
        logger.info("🔄 重新加载实体数据...")
        
        # 清空现有节点（只清空实体节点，保留其他节点）
        nodes_to_remove = []
        for node_id, attrs in self.knowledge_graph.graph.nodes(data=True):
            if attrs.get('type') in ['character', 'location', 'item', 'event', 'concept']:
                nodes_to_remove.append(node_id)
        
        for node_id in nodes_to_remove:
            self.knowledge_graph.graph.remove_node(node_id)
        
        # 重新加载
        self._load_entities_from_json()
        
        logger.info("✅ 实体数据重新加载完成")

    # --- Interface for Hot and Warm Memory ---

    def add_conversation(self, user_input: str, ai_response: str):
        """向热记忆中添加一轮对话。"""
        self.basic_memory.add_conversation(user_input, ai_response)
        self._data_changed = True  # 标记数据已变化

    def get_recent_conversation(self, turns: int = 5) -> str:
        """获取最近几轮的对话历史。"""
        return self.basic_memory.get_context(recent_turns=turns)

    def update_state(self, key: str, value: Any):
        """更新温记忆中的状态。"""
        self.basic_memory.update_state(key, value)
        self._data_changed = True  # 标记数据已变化

    def get_state(self, key: str) -> Any:
        """从温记忆中获取状态。"""
        return self.basic_memory.get_state(key)

    # --- Interface for Cold Memory (Knowledge Graph) ---

    def add_or_update_node(self, node_id: str, node_type: str, **kwargs):
        """在知识图谱中添加或更新节点，带有冲突解决机制。"""
        self.knowledge_graph.add_or_update_node_with_conflict_resolution(node_id, node_type, **kwargs)
        self._data_changed = True  # 标记数据已变化

    def add_edge(self, source: str, target: str, relationship: str, **kwargs):
        """在知识图谱中添加关系。"""
        self.knowledge_graph.add_edge(source, target, relationship, **kwargs)
        self._data_changed = True  # 标记数据已变化

    def delete_node(self, node_id: str) -> bool:
        """从知识图谱中删除节点及其所有关系。"""
        result = self.knowledge_graph.delete_node(node_id)
        if result:
            self._data_changed = True  # 标记数据已变化
        return result

    def delete_edge(self, source: str, target: str, relationship: str = None) -> bool:
        """从知识图谱中删除边。"""
        result = self.knowledge_graph.delete_edge(source, target, relationship)
        if result:
            self._data_changed = True  # 标记数据已变化
        return result

    def mark_node_as_deleted(self, node_id: str, reason: str = ""):
        """软删除节点，标记为已删除但保留历史记录。"""
        self.knowledge_graph.mark_node_as_deleted(node_id, reason)

    def get_active_nodes(self) -> List[str]:
        """获取所有活跃（未删除）的节点。"""
        return self.knowledge_graph.get_active_nodes()

    def cleanup_old_deleted_nodes(self, days_threshold: int = 30) -> int:
        """清理超过指定天数的已删除节点。"""
        return self.knowledge_graph.cleanup_deleted_nodes(days_threshold)

    def get_knowledge_graph_context(self, entity_ids: List[str], depth: int = 1) -> str:
        """
        从知识图谱中为指定实体提取上下文。

        Args:
            entity_ids (List[str]): 需要检索的核心实体ID。
            depth (int): 检索深度。

        Returns:
            str: 知识图谱子图的文本表示。
        """
        if not entity_ids:
            return "No entities provided for knowledge graph retrieval."
        
        subgraph = self.knowledge_graph.get_subgraph_for_context(entity_ids, depth)
        return self.knowledge_graph.to_text_representation(subgraph)

    # --- Unified Retrieval ---

    def retrieve_context_for_prompt(self, entities_in_query: List[str], recent_turns: int = 3) -> str:
        """
        为LLM的提示词构建完整的上下文。
        整合了所有记忆层的信息。

        Args:
            entities_in_query (List[str]): 从当前用户输入中识别出的核心实体。
            recent_turns (int): 要包含的最近对话轮数。

        Returns:
            str: 格式化后的、可直接用于Prompt的上下文字符串。
        """
        # 1. 从热记忆获取最近对话
        conversation_context = self.get_recent_conversation(turns=recent_turns)
        
        # 2. 从温记忆获取关键状态 (这里可以根据实体来决定查询哪些状态)
        # 简单起见，我们先假设有一个全局状态需要展示
        world_time = self.get_state("world_time")
        world_state_context = f"[Current World State]\n- World Time: {world_time if world_time else 'Not set'}\n"

        # 3. 从冷记忆获取相关的知识图谱信息
        graph_context = self.get_knowledge_graph_context(entities_in_query, depth=1)

        # 4. 组合所有上下文
        full_context = (
            f"## Recent Conversation History\n{conversation_context}\n\n"
            f"## {world_state_context}\n"
            f"## Relevant Knowledge Graph\n{graph_context}"
        )

        logger.info("Generated combined context for prompt.")
        return full_context

    def save_all_memory(self):
        """只在有数据变化时保存记忆状态。"""
        if not self._data_changed:
            logger.info("没有数据变化，跳过保存")
            return
        
        # 保存热、温记忆
        self.basic_memory.save_to_file()
        
        # 保存冷记忆 (知识图谱)
        if self.graph_save_path:
            self.knowledge_graph.save_graph(self.graph_save_path)
        else:
            logger.warning("Knowledge graph save path is not set. Graph will not be saved.")
        
        # 重置变化标记
        self._data_changed = False
        logger.info("记忆状态已保存")
    
    def clear_all(self):
        """清空所有记忆层的数据"""
        try:
            # 清空热、温记忆
            self.basic_memory.conversation_history.clear()
            self.basic_memory.state_table.clear()
            
            # 清空冷记忆（知识图谱）
            self.knowledge_graph.clear()
            
            # 同步清空entities.json文件
            self.sync_entities_to_json()
            
            # 重置变化标记
            self._data_changed = True
            self._last_conversation_count = 0
            
            logger.info("所有记忆层数据已清空，包括entities.json文件")
            
        except Exception as e:
            logger.error(f"清空记忆数据失败: {e}")
            raise
