from collections import deque, defaultdict, Counter
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
import json
import os
import time
from pathlib import Path


from src.memory.basic_memory import BasicMemory
from src.graph.knowledge_graph import KnowledgeGraph


class EntityImportanceEvaluator:
    """实体重要性评估器 - 解决注意力分散问题"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.collective_weight = self.config.get('collective_weight', 0.6)
        self.holistic_weight = self.config.get('holistic_weight', 0.4)
        self.importance_threshold = self.config.get('importance_threshold', 0.3)
        self.max_context_entities = self.config.get('max_context_entities', 15)

        # 实体类型权重 - 不同类型的实体有不同的基础重要性
        self.entity_type_weights = {
            'character': 1.0,      # 角色最重要
            'location': 0.8,       # 地点次之
            'item': 0.7,          # 物品
            'concept': 0.4,       # 概念类实体权重较低
            'event': 0.6          # 事件
        }

        # 关系类型权重 - 不同关系的重要性
        self.relationship_weights = {
            '拥有': 0.8, '控制': 0.9, '管理': 0.8, '创立': 0.7,
            '位于': 0.6, '使用': 0.5, '遵循': 0.3, '研发': 0.4,
            '实施': 0.4, '计划': 0.2, '支持': 0.3, '引导': 0.3,
            '驱动': 0.3, '实现': 0.3, '互补': 0.2, '签订': 0.5,
            '被影响': 0.6, '制造': 0.6, '属于': 0.4, '继承': 0.7,
            '受控于': 0.8, '受约束于': 0.7, '曾经控制': 0.5
        }

    def evaluate_collective_importance(self, entity_name: str, entity_data: Dict,
                                     conversation_history: List[Dict] = None) -> float:
        """集体重要性评估 - 基于对话历史中的提及频率和上下文相关性"""
        if not conversation_history:
            return 0.5  # 默认中等重要性

        mention_count = 0
        recent_mentions = 0
        context_relevance = 0.0

        # 统计实体在对话中的提及情况
        for i, message in enumerate(conversation_history):
            content = message.get('content', '').lower()
            entity_lower = entity_name.lower()

            # 检查实体名称或描述是否在消息中出现
            if entity_lower in content or any(
                keyword.lower() in content
                for keyword in entity_data.get('attributes', {}).get('name', '').split()
                if keyword
            ):
                mention_count += 1
                # 最近的消息权重更高
                if i >= len(conversation_history) - 5:
                    recent_mentions += 1

                # 计算上下文相关性（简化版本）
                context_relevance += 1.0 / (len(conversation_history) - i)

        # 归一化评分
        total_messages = len(conversation_history)
        mention_frequency = mention_count / max(total_messages, 1)
        recent_relevance = recent_mentions / min(5, total_messages)

        collective_score = (mention_frequency * 0.4 +
                          recent_relevance * 0.4 +
                          min(context_relevance, 1.0) * 0.2)

        return min(collective_score, 1.0)

    def evaluate_holistic_importance(self, entity_name: str, entity_data: Dict,
                                   all_relationships: List[Dict]) -> float:
        """整体重要性评估 - 基于实体类型、关系数量和关系质量"""

        # 1. 基于实体类型的基础权重
        entity_type = entity_data.get('type', 'concept')
        base_weight = self.entity_type_weights.get(entity_type, 0.5)

        # 2. 计算关系重要性
        entity_relationships = [
            rel for rel in all_relationships
            if rel.get('source') == entity_name or rel.get('target') == entity_name
        ]

        if not entity_relationships:
            return base_weight * 0.5  # 没有关系的实体重要性降低

        # 关系质量评分
        relationship_score = 0.0
        for rel in entity_relationships:
            rel_type = rel.get('relationship', '')
            rel_weight = self.relationship_weights.get(rel_type, 0.3)
            relationship_score += rel_weight

        # 归一化关系评分
        avg_relationship_score = relationship_score / len(entity_relationships)

        # 3. 关系数量惩罚 - 关系过多的实体可能是"大合集"问题
        relationship_count = len(entity_relationships)
        if relationship_count > 10:
            # 对关系过多的实体进行惩罚
            count_penalty = max(0.3, 1.0 - (relationship_count - 10) * 0.05)
        else:
            count_penalty = 1.0

        # 4. 特殊规则：主角色保持较高重要性
        is_main_character = entity_data.get('attributes', {}).get('is_main_character', False)
        main_char_bonus = 0.3 if is_main_character else 0.0

        holistic_score = (base_weight * 0.4 +
                         avg_relationship_score * 0.4 +
                         main_char_bonus) * count_penalty

        return min(holistic_score, 1.0)

    def compute_aggregated_importance(self, entity_name: str, entity_data: Dict,
                                    all_relationships: List[Dict],
                                    conversation_history: List[Dict] = None) -> float:
        """计算聚合重要性评分"""
        collective = self.evaluate_collective_importance(entity_name, entity_data, conversation_history)
        holistic = self.evaluate_holistic_importance(entity_name, entity_data, all_relationships)

        aggregated_score = (self.collective_weight * collective +
                          self.holistic_weight * holistic)

        return aggregated_score


class AttentionAwareContextBuilder:
    """注意力感知的上下文构建器"""

    def __init__(self, importance_evaluator: EntityImportanceEvaluator):
        self.importance_evaluator = importance_evaluator

    def filter_and_rank_entities(self, entities_data: Dict, relationships_data: List[Dict],
                                conversation_history: List[Dict] = None) -> List[Tuple[str, Dict, float]]:
        """过滤并排序实体"""
        ranked_entities = []

        for entity_name, entity_data in entities_data.items():
            importance_score = self.importance_evaluator.compute_aggregated_importance(
                entity_name, entity_data, relationships_data, conversation_history
            )

            # 只保留重要性超过阈值的实体
            if importance_score >= self.importance_evaluator.importance_threshold:
                ranked_entities.append((entity_name, entity_data, importance_score))

        # 按重要性排序
        ranked_entities.sort(key=lambda x: x[2], reverse=True)

        # 限制数量
        max_entities = self.importance_evaluator.max_context_entities
        return ranked_entities[:max_entities]

    def build_optimized_context(self, character_name: str, entities_data: Dict,
                              relationships_data: List[Dict],
                              conversation_history: List[Dict] = None) -> str:
        """构建优化的上下文"""

        # 1. 获取主角色信息
        main_character = None
        for entity_name, entity_data in entities_data.items():
            if (entity_data.get('attributes', {}).get('is_main_character', False) or
                entity_name.endswith(character_name)):
                main_character = (entity_name, entity_data)
                break

        if not main_character:
            logger.warning(f"未找到主角色: {character_name}")
            return "角色信息不完整"

        # 2. 过滤和排序其他实体
        other_entities = {k: v for k, v in entities_data.items() if k != main_character[0]}
        filtered_entities = self.filter_and_rank_entities(
            other_entities, relationships_data, conversation_history
        )

        # 3. 构建分层上下文
        context_parts = []

        # 主角色信息（始终包含）
        main_name, main_data = main_character
        main_desc = main_data.get('description', '')
        main_attrs = main_data.get('attributes', {})

        context_parts.append(f"【核心角色】{main_name}: {main_desc}")

        if main_attrs.get('personality_traits'):
            context_parts.append(f"性格特征: {', '.join(main_attrs['personality_traits'])}")

        if main_attrs.get('background'):
            context_parts.append(f"背景: {main_attrs['background']}")

        # 重要关联实体（按重要性分组）
        if filtered_entities:
            high_importance = [e for e in filtered_entities if e[2] > 0.7]
            medium_importance = [e for e in filtered_entities if 0.4 <= e[2] <= 0.7]

            if high_importance:
                context_parts.append("\n【核心关联】")
                for entity_name, entity_data, score in high_importance[:5]:
                    desc = entity_data.get('description', '')
                    context_parts.append(f"- {entity_name}: {desc}")

            if medium_importance and len(high_importance) < 8:
                context_parts.append("\n【相关信息】")
                remaining_slots = 8 - len(high_importance)
                for entity_name, entity_data, score in medium_importance[:remaining_slots]:
                    desc = entity_data.get('description', '')
                    # 对中等重要性的实体进行描述简化
                    short_desc = desc[:100] + "..." if len(desc) > 100 else desc
                    context_parts.append(f"- {entity_name}: {short_desc}")

        return "\n".join(context_parts)


class GRAGMemory:
    """
    GRAG三层记忆系统，整合了热、温、冷三种记忆。
    - 热记忆 (Hot Memory): 最近的对话历史，使用 BasicMemory 的 deque。
    - 温记忆 (Warm Memory): 关键状态键值对，使用 BasicMemory 的 state_table。
    - 冷记忆 (Cold Memory): 结构化的知识图谱，使用 KnowledgeGraph。
    """

    def __init__(self, hot_memory_size: int = 10, graph_save_path: Optional[str] = None,
                 entities_json_path: Optional[str] = None, auto_load_entities: bool = True,
                 attention_config: Dict[str, Any] = None):
        """
        初始化三层记忆系统。

        Args:
            hot_memory_size (int): 热记忆要保留的最近对话轮数。
            graph_save_path (Optional[str]): 知识图谱的保存/加载路径。
            entities_json_path (Optional[str]): 实体JSON文件的保存/加载路径。
            auto_load_entities (bool): 是否自动加载entities.json文件。默认True，设为False时需要手动调用加载。
            attention_config (Dict[str, Any]): 注意力机制配置参数。
        """
        # 热、温记忆层 (继承自BasicMemory的功能)
        self.basic_memory = BasicMemory(max_size=hot_memory_size)

        # 冷记忆层
        self.knowledge_graph = KnowledgeGraph()
        self.graph_save_path = graph_save_path
        self.entities_json_path = entities_json_path or str(Path(__file__).parent.parent.parent / "data" / "entities.json")

        # 注意力机制组件
        self.importance_evaluator = EntityImportanceEvaluator(attention_config)
        self.context_builder = AttentionAwareContextBuilder(self.importance_evaluator)

        # 缓存优化后的上下文
        self._context_cache = {}
        self._cache_timestamp = {}

        if self.graph_save_path:
            self.knowledge_graph.load_graph(self.graph_save_path)

        # 根据参数决定是否自动加载UI中的实体数据到知识图谱
        if auto_load_entities:
            self._load_entities_from_json()

        # 数据变化追踪
        self._data_changed = False
        self._last_conversation_count = 0

        logger.info("GRAGMemory initialized with Hot, Warm, and Cold memory layers + Attention Mechanism.")

    def _load_entities_from_json(self):
        """从UI的entities.json文件加载实体到知识图谱中"""
        import json
        import os
        from pathlib import Path

        # 使用配置的实体文件路径
        entities_file = Path(self.entities_json_path)

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
            
            logger.info(f"[OK] 成功从 entities.json 加载了 {entities_loaded} 个实体到知识图谱")
            
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
            
            logger.info(f"[OK] 成功从 entities.json 加载了 {relationships_loaded} 个关系到知识图谱")
            
        except Exception as e:
            logger.error(f"❌ 从 entities.json 加载实体失败: {e}")
            logger.exception("详细错误信息:")
    
    def sync_entities_to_json(self):
        """将知识图谱中的实体同步到entities.json文件"""
        import json
        import time
        from pathlib import Path

        # 使用配置的实体文件路径
        entities_file = Path(self.entities_json_path)
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
            
            logger.info(f"[OK] 成功同步 {len(entities)} 个实体和 {len(relationships)} 个关系到 entities.json")
            
        except Exception as e:
            logger.error(f"❌ 同步实体到 entities.json 失败: {e}")
            logger.exception("详细错误信息:")

    def set_entities_json_path(self, entities_json_path: str):
        """动态设置entities.json文件路径"""
        self.entities_json_path = entities_json_path
        logger.info(f"🔄 更新entities.json路径: {entities_json_path}")

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
        
        logger.info("[OK] 实体数据重新加载完成")

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

    def rename_node(self, old_node_id: str, new_node_id: str) -> bool:
        """重命名节点，保持所有关系不变。"""
        result = self.knowledge_graph.rename_node(old_node_id, new_node_id)
        if result:
            self._data_changed = True  # 标记数据已变化
        return result

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

        # 同步实体和关系到JSON文件（确保UI能正确显示）
        self.sync_entities_to_json()

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

    def _get_conversation_history_for_attention(self) -> List[Dict]:
        """获取用于注意力机制分析的对话历史"""
        try:
            # 将BasicMemory的conversation_history转换为注意力机制需要的格式
            conversation_list = []

            for conv in self.basic_memory.conversation_history:
                # 添加用户消息
                if 'user' in conv:
                    conversation_list.append({
                        'role': 'user',
                        'content': conv['user'],
                        'timestamp': conv.get('timestamp', '')
                    })

                # 添加AI回复
                if 'ai' in conv:
                    conversation_list.append({
                        'role': 'assistant',
                        'content': conv['ai'],
                        'timestamp': conv.get('timestamp', '')
                    })

            return conversation_list

        except Exception as e:
            logger.warning(f"获取对话历史失败: {e}")
            return []

    def get_optimized_character_context(self, character_name: str,
                                      use_cache: bool = True) -> str:
        """
        获取角色的优化上下文 - 解决注意力分散问题

        Args:
            character_name (str): 角色名称
            use_cache (bool): 是否使用缓存

        Returns:
            str: 优化后的角色上下文
        """
        try:
            # 检查缓存
            cache_key = f"context_{character_name}"
            current_time = time.time()

            if (use_cache and cache_key in self._context_cache and
                current_time - self._cache_timestamp.get(cache_key, 0) < 300):  # 5分钟缓存
                logger.debug(f"使用缓存的角色上下文: {character_name}")
                return self._context_cache[cache_key]

            # 从entities.json加载数据
            entities_data = {}
            relationships_data = []

            if os.path.exists(self.entities_json_path):
                with open(self.entities_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    # 转换实体数据格式
                    for entity in data.get('entities', []):
                        entity_name = entity.get('name', '')
                        if entity_name:
                            entities_data[entity_name] = entity

                    relationships_data = data.get('relationships', [])

            if not entities_data:
                logger.warning(f"未找到角色 {character_name} 的实体数据")
                return f"角色 {character_name} 的信息暂不可用"

            # 获取对话历史
            conversation_history = self._get_conversation_history_for_attention()

            # 构建优化上下文
            optimized_context = self.context_builder.build_optimized_context(
                character_name, entities_data, relationships_data, conversation_history
            )

            # 更新缓存
            self._context_cache[cache_key] = optimized_context
            self._cache_timestamp[cache_key] = current_time

            # 记录优化效果
            total_entities = len(entities_data)
            filtered_count = len([
                e for e in entities_data.values()
                if self.importance_evaluator.compute_aggregated_importance(
                    e.get('name', ''), e, relationships_data, conversation_history
                ) >= self.importance_evaluator.importance_threshold
            ])

            logger.info(f"角色上下文优化完成: {character_name}, "
                       f"实体数量 {total_entities} -> {filtered_count} "
                       f"(减少 {((total_entities - filtered_count) / total_entities * 100):.1f}%)")

            return optimized_context

        except Exception as e:
            logger.error(f"获取优化角色上下文失败: {e}")
            return f"角色 {character_name} 的信息加载失败: {str(e)}"

    def get_entity_importance_report(self, character_name: str) -> Dict[str, Any]:
        """
        获取实体重要性分析报告

        Args:
            character_name (str): 角色名称

        Returns:
            Dict[str, Any]: 重要性分析报告
        """
        try:
            # 加载数据
            entities_data = {}
            relationships_data = []

            if os.path.exists(self.entities_json_path):
                with open(self.entities_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for entity in data.get('entities', []):
                        entity_name = entity.get('name', '')
                        if entity_name:
                            entities_data[entity_name] = entity
                    relationships_data = data.get('relationships', [])

            if not entities_data:
                return {"error": "未找到实体数据"}

            conversation_history = self._get_conversation_history_for_attention()

            # 计算所有实体的重要性
            entity_scores = []
            for entity_name, entity_data in entities_data.items():
                importance_score = self.importance_evaluator.compute_aggregated_importance(
                    entity_name, entity_data, relationships_data, conversation_history
                )

                collective_score = self.importance_evaluator.evaluate_collective_importance(
                    entity_name, entity_data, conversation_history
                )

                holistic_score = self.importance_evaluator.evaluate_holistic_importance(
                    entity_name, entity_data, relationships_data
                )

                entity_scores.append({
                    'name': entity_name,
                    'type': entity_data.get('type', 'unknown'),
                    'importance_score': importance_score,
                    'collective_score': collective_score,
                    'holistic_score': holistic_score,
                    'above_threshold': importance_score >= self.importance_evaluator.importance_threshold
                })

            # 排序
            entity_scores.sort(key=lambda x: x['importance_score'], reverse=True)

            # 统计信息
            total_entities = len(entity_scores)
            above_threshold = len([e for e in entity_scores if e['above_threshold']])

            report = {
                'character_name': character_name,
                'total_entities': total_entities,
                'entities_above_threshold': above_threshold,
                'filter_ratio': (total_entities - above_threshold) / total_entities if total_entities > 0 else 0,
                'threshold': self.importance_evaluator.importance_threshold,
                'max_context_entities': self.importance_evaluator.max_context_entities,
                'entity_scores': entity_scores[:20],  # 只返回前20个
                'config': {
                    'collective_weight': self.importance_evaluator.collective_weight,
                    'holistic_weight': self.importance_evaluator.holistic_weight,
                    'importance_threshold': self.importance_evaluator.importance_threshold,
                    'max_context_entities': self.importance_evaluator.max_context_entities
                }
            }

            return report

        except Exception as e:
            logger.error(f"生成重要性报告失败: {e}")
            return {"error": str(e)}

    def update_attention_config(self, new_config: Dict[str, Any]):
        """更新注意力机制配置"""
        try:
            # 更新配置
            for key, value in new_config.items():
                if hasattr(self.importance_evaluator, key):
                    setattr(self.importance_evaluator, key, value)
                    logger.info(f"更新注意力配置: {key} = {value}")

            # 清空缓存以应用新配置
            self._context_cache.clear()
            self._cache_timestamp.clear()

            logger.info("注意力机制配置已更新")

        except Exception as e:
            logger.error(f"更新注意力配置失败: {e}")
            raise
