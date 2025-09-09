import networkx as nx
import json
from loguru import logger
from typing import List, Dict, Any, Optional, Tuple

class KnowledgeGraph:
    """
    使用 NetworkX 管理知识图谱，用于GRAG的核心组件。
    负责节点（角色、物品、地点等）和关系（拥有、位于、敌对等）的增删改查。
    """

    def __init__(self):
        """初始化一个有向图。"""
        self.graph = nx.DiGraph()
        logger.info("KnowledgeGraph initialized with a directed graph.")

    def add_or_update_node(self, node_id: str, node_type: str, **kwargs):
        """
        添加一个新节点或更新现有节点的属性。
        节点ID是唯一的标识符。

        Args:
            node_id (str): 节点的唯一ID，例如 "player", "sword_of_destiny"。
            node_type (str): 节点的类型，例如 "character", "item", "location"。
            **kwargs: 节点的其他属性，例如 {"health": 100, "status": "alive"}。
        """
        attributes = kwargs.copy()
        attributes['type'] = node_type

        if self.graph.has_node(node_id):
            self.graph.nodes[node_id].update(attributes)
            logger.info(f"Node '{node_id}' updated with attributes: {attributes}")
        else:
            self.graph.add_node(node_id, **attributes)
            logger.info(f"Node '{node_id}' added with attributes: {attributes}")

    def add_edge(self, source_node: str, target_node: str, relationship: str, **kwargs):
        """
        在两个节点之间添加一条带标签的关系边。

        Args:
            source_node (str): 关系发起节点的ID。
            target_node (str): 关系目标节点的ID。
            relationship (str): 关系的描述，例如 "owns", "located_in", "is_hostile_to"。
            **kwargs: 关系边的其他属性。
        """
        if not self.graph.has_node(source_node):
            logger.warning(f"Source node '{source_node}' not found. Edge not added.")
            return
        if not self.graph.has_node(target_node):
            logger.warning(f"Target node '{target_node}' not found. Edge not added.")
            return

        self.graph.add_edge(source_node, target_node, relationship=relationship, **kwargs)
        logger.info(f"Edge added from '{source_node}' to '{target_node}' with relationship '{relationship}'.")

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个节点及其所有属性。

        Args:
            node_id (str): 节点的ID。

        Returns:
            Optional[Dict[str, Any]]: 包含节点属性的字典，如果节点不存在则返回None。
        """
        if self.graph.has_node(node_id):
            return self.graph.nodes[node_id]
        return None

    def get_subgraph_for_context(self, entity_ids: List[str], depth: int = 1) -> nx.DiGraph:
        """
        为给定的实体列表提取一个连通子图，用于生成上下文。
        这实现了你计划中的“动态子图检索”。

        Args:
            entity_ids (List[str]): 需要作为检索核心的实体ID列表。
            depth (int): 从核心实体向外扩展的深度。默认为1，即只包含直接邻居。

        Returns:
            nx.DiGraph: 包含相关实体及其关系的子图。
        """
        relevant_nodes = set()
        for entity_id in entity_ids:
            if self.graph.has_node(entity_id):
                relevant_nodes.add(entity_id)
                subgraph = nx.ego_graph(self.graph, entity_id, radius=depth)
                relevant_nodes.update(subgraph.nodes)
        
        return self.graph.subgraph(relevant_nodes)

    def to_text_representation(self, subgraph: Optional[nx.DiGraph] = None) -> str:
        """
        将图（或子图）转换为文本表示，以便输入到LLM。
        """
        target_graph = subgraph if subgraph is not None else self.graph
        
        if not target_graph.nodes:
            return "The knowledge graph is empty."

        text_parts = ["[Nodes]"]
        for node, attrs in target_graph.nodes(data=True):
            attr_list = [f"{k}: {repr(v)}" if isinstance(v, str) else f"{k}: {v}" for k, v in attrs.items() if k != 'type']
            attr_str = ", ".join(attr_list)
            if attr_str:
                text_parts.append(f"- {node} (type: {attrs.get('type', 'N/A')}): {{ {attr_str} }}")
            else:
                text_parts.append(f"- {node} (type: {attrs.get('type', 'N/A')})")

        text_parts.append("\n[Relationships]")
        for source, target, attrs in target_graph.edges(data=True):
            rel = attrs.get('relationship', 'related_to')
            attr_list = [f"{k}: {repr(v)}" if isinstance(v, str) else f"{k}: {v}" for k, v in attrs.items() if k != 'relationship']
            attr_str = ", ".join(attr_list)
            if attr_str:
                text_parts.append(f"- {source} -> {target} ({rel}): {{ {attr_str} }}")
            else:
                text_parts.append(f"- {source} -> {target} ({rel})")
        
        return "\n".join(text_parts)

    def search_nodes(self, query: str) -> List[str]:
        """
        在知识图谱中搜索匹配查询字符串的节点。
        搜索范围包括节点ID和所有节点属性的值。
        """
        if not query: # 如果查询为空，返回所有节点
            return sorted(list(self.graph.nodes()))

        matching_nodes = []
        query_lower = query.lower()

        for node_id, attrs in self.graph.nodes(data=True):
            # 检查节点ID是否匹配
            if query_lower in node_id.lower():
                matching_nodes.append(node_id)
                continue # 找到匹配后，不再检查属性

            # 检查节点属性值是否匹配
            for value in attrs.values():
                if isinstance(value, str) and query_lower in value.lower():
                    matching_nodes.append(node_id)
                    break # 找到匹配后，跳出属性循环
                elif not isinstance(value, str) and query_lower in str(value).lower():
                    matching_nodes.append(node_id)
                    break
        
        return sorted(list(set(matching_nodes))) # 去重并排序

    def save_graph(self, file_path: str):
        """
        将图保存到文件。在保存前，将所有list类型的属性转换为JSON字符串。
        """
        # 创建一个图的深拷贝以进行序列化，避免修改原始图
        graph_to_save = self.graph.copy()
        for _, data in graph_to_save.nodes(data=True):
            for key, value in data.items():
                if isinstance(value, list):
                    data[key] = json.dumps(value)
        try:
            nx.write_graphml(graph_to_save, file_path)
            logger.info(f"Graph saved to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save graph to {file_path}: {e}")

    def load_graph(self, file_path: str):
        """
        从文件加载图。在加载后，将所有JSON字符串的属性转换回list。
        """
        try:
            self.graph = nx.read_graphml(file_path)
            for _, data in self.graph.nodes(data=True):
                for key, value in data.items():
                    # 检查值是否为字符串，并且看起来像一个JSON列表
                    if isinstance(value, str) and value.startswith('[') and value.endswith(']'):
                        try:
                            data[key] = json.loads(value)
                        except json.JSONDecodeError:
                            # 如果解析失败，则保持原样
                            pass
            logger.info(f"Graph loaded from {file_path} and attributes deserialized.")
        except FileNotFoundError:
            logger.warning(f"Graph file not found at {file_path}. Starting with an empty graph.")
        except Exception as e:
            logger.error(f"Failed to load graph from {file_path}: {e}")

    def delete_node(self, node_id: str) -> bool:
        """
        删除节点及其所有相关边。
        
        Args:
            node_id (str): 要删除的节点ID
            
        Returns:
            bool: 删除成功返回True，节点不存在返回False
        """
        if not self.graph.has_node(node_id):
            logger.warning(f"Node '{node_id}' not found. Cannot delete.")
            return False
        
        # 记录删除的边数量用于日志
        in_degree = self.graph.in_degree(node_id)
        out_degree = self.graph.out_degree(node_id)
        
        self.graph.remove_node(node_id)
        logger.info(f"Node '{node_id}' deleted along with {in_degree + out_degree} edges.")
        return True

    def delete_edge(self, source_node: str, target_node: str, relationship: str = None) -> bool:
        """
        删除指定的边。如果指定了关系类型，只删除匹配的边。
        
        Args:
            source_node (str): 起始节点ID
            target_node (str): 目标节点ID
            relationship (str, optional): 关系类型，如果指定则只删除匹配的边
            
        Returns:
            bool: 删除成功返回True，边不存在返回False
        """
        if not self.graph.has_edge(source_node, target_node):
            logger.warning(f"Edge from '{source_node}' to '{target_node}' not found. Cannot delete.")
            return False
        
        if relationship:
            # 检查边是否有指定的关系类型
            edge_data = self.graph.get_edge_data(source_node, target_node)
            if edge_data.get('relationship') != relationship:
                logger.warning(f"Edge from '{source_node}' to '{target_node}' with relationship '{relationship}' not found.")
                return False
        
        self.graph.remove_edge(source_node, target_node)
        logger.info(f"Edge from '{source_node}' to '{target_node}' deleted.")
        return True

    def resolve_attribute_conflict(self, node_id: str, attribute: str, old_value: Any, new_value: Any) -> Any:
        """
        解决属性冲突，返回应该使用的最终值。
        
        Args:
            node_id (str): 节点ID
            attribute (str): 属性名
            old_value: 旧值
            new_value: 新值
            
        Returns:
            Any: 解决冲突后的值
        """
        # 数值类型的智能合并
        if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            if attribute in ["health", "hp", "血量"]:
                # 血量取较新的值，但不超过最大值
                max_health = self.graph.nodes[node_id].get("max_health", new_value)
                return min(new_value, max_health)
            elif attribute in ["max_health", "max_hp", "最大血量"]:
                # 最大血量取较大值
                return max(old_value, new_value)
            elif attribute in ["level", "等级"]:
                # 等级取较大值（通常只会增长）
                return max(old_value, new_value)
            elif attribute in ["experience", "exp", "经验"]:
                # 经验取较大值
                return max(old_value, new_value)
        
        # 列表类型的合并
        if isinstance(old_value, list) and isinstance(new_value, list):
            # 合并列表，去重
            combined = list(set(old_value + new_value))
            logger.info(f"Merged list attribute '{attribute}' for node '{node_id}': {len(old_value)} + {len(new_value)} → {len(combined)}")
            return combined
        
        # 字符串类型的处理
        if isinstance(old_value, str) and isinstance(new_value, str):
            if attribute in ["location", "位置"]:
                # 位置信息，新值优先
                logger.info(f"Location updated for '{node_id}': '{old_value}' → '{new_value}'")
                return new_value
            elif attribute in ["status", "状态"]:
                # 状态信息，新值优先
                logger.info(f"Status updated for '{node_id}': '{old_value}' → '{new_value}'")
                return new_value
        
        # 默认情况：新值优先，但记录变化
        if old_value != new_value:
            logger.info(f"Attribute conflict resolved for '{node_id}.{attribute}': '{old_value}' → '{new_value}'")
        
        return new_value

    def add_or_update_node_with_conflict_resolution(self, node_id: str, node_type: str, **kwargs):
        """
        添加或更新节点，带有冲突解决机制。
        
        Args:
            node_id (str): 节点ID
            node_type (str): 节点类型
            **kwargs: 节点属性
        """
        attributes = kwargs.copy()
        attributes['type'] = node_type
        
        if self.graph.has_node(node_id):
            # 节点已存在，进行冲突解决
            existing_attrs = self.graph.nodes[node_id]
            resolved_attrs = existing_attrs.copy()
            
            for key, new_value in attributes.items():
                if key in existing_attrs:
                    old_value = existing_attrs[key]
                    resolved_value = self.resolve_attribute_conflict(node_id, key, old_value, new_value)
                    resolved_attrs[key] = resolved_value
                else:
                    resolved_attrs[key] = new_value
            
            self.graph.nodes[node_id].update(resolved_attrs)
            logger.info(f"Node '{node_id}' updated with conflict resolution. Attributes: {attributes}")
        else:
            # 新节点，直接添加
            self.graph.add_node(node_id, **attributes)
            logger.info(f"Node '{node_id}' added with attributes: {attributes}")

    def get_node_history(self, node_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        获取节点的变更历史（如果启用了历史跟踪）。
        
        Args:
            node_id (str): 节点ID
            
        Returns:
            Optional[List[Dict[str, Any]]]: 变更历史列表
        """
        if self.graph.has_node(node_id):
            return self.graph.nodes[node_id].get('_history', [])
        return None

    def mark_node_as_deleted(self, node_id: str, reason: str = ""):
        """
        标记节点为已删除状态，而不是真正删除（软删除）。
        适用于需要保留历史记录的场景。
        
        Args:
            node_id (str): 节点ID
            reason (str): 删除原因
        """
        if not self.graph.has_node(node_id):
            logger.warning(f"Node '{node_id}' not found. Cannot mark as deleted.")
            return
        
        self.graph.nodes[node_id]['_deleted'] = True
        self.graph.nodes[node_id]['_deleted_reason'] = reason
        
        from datetime import datetime
        self.graph.nodes[node_id]['_deleted_timestamp'] = datetime.now().isoformat()
        
        logger.info(f"Node '{node_id}' marked as deleted. Reason: {reason}")

    def get_active_nodes(self) -> List[str]:
        """
        获取所有未被标记为删除的节点。
        
        Returns:
            List[str]: 活跃节点ID列表
        """
        return [node_id for node_id, data in self.graph.nodes(data=True) 
                if not data.get('_deleted', False)]

    def cleanup_deleted_nodes(self, days_threshold: int = 30):
        """
        清理标记为删除超过指定天数的节点。
        
        Args:
            days_threshold (int): 删除阈值天数
        """
        from datetime import datetime, timedelta
        
        current_time = datetime.now()
        nodes_to_remove = []
        
        for node_id, data in self.graph.nodes(data=True):
            if data.get('_deleted', False):
                deleted_time_str = data.get('_deleted_timestamp')
                if deleted_time_str:
                    try:
                        deleted_time = datetime.fromisoformat(deleted_time_str)
                        if (current_time - deleted_time).days > days_threshold:
                            nodes_to_remove.append(node_id)
                    except Exception as e:
                        logger.warning(f"Failed to parse deleted timestamp for node '{node_id}': {e}")
        
        for node_id in nodes_to_remove:
            self.graph.remove_node(node_id)
            logger.info(f"Permanently removed deleted node '{node_id}' after {days_threshold} days.")
        
        return len(nodes_to_remove)
    
    def clear(self):
        """清空整个知识图谱"""
        try:
            node_count = self.graph.number_of_nodes()
            edge_count = self.graph.number_of_edges()
            
            self.graph.clear()
            
            logger.info(f"知识图谱已清空: 删除了 {node_count} 个节点和 {edge_count} 条边")
            
        except Exception as e:
            logger.error(f"清空知识图谱失败: {e}")
            raise