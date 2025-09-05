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

        logger.info("GRAGMemory initialized with Hot, Warm, and Cold memory layers.")

    # --- Interface for Hot and Warm Memory ---

    def add_conversation(self, user_input: str, ai_response: str):
        """向热记忆中添加一轮对话。"""
        self.basic_memory.add_conversation(user_input, ai_response)

    def get_recent_conversation(self, turns: int = 5) -> str:
        """获取最近几轮的对话历史。"""
        return self.basic_memory.get_context(recent_turns=turns)

    def update_state(self, key: str, value: Any):
        """更新温记忆中的状态。"""
        self.basic_memory.update_state(key, value)

    def get_state(self, key: str) -> Any:
        """从温记忆中获取状态。"""
        return self.basic_memory.get_state(key)

    # --- Interface for Cold Memory (Knowledge Graph) ---

    def add_or_update_node(self, node_id: str, node_type: str, **kwargs):
        """在知识图谱中添加或更新节点，带有冲突解决机制。"""
        self.knowledge_graph.add_or_update_node_with_conflict_resolution(node_id, node_type, **kwargs)

    def add_edge(self, source: str, target: str, relationship: str, **kwargs):
        """在知识图谱中添加关系。"""
        self.knowledge_graph.add_edge(source, target, relationship, **kwargs)

    def delete_node(self, node_id: str) -> bool:
        """从知识图谱中删除节点及其所有关系。"""
        return self.knowledge_graph.delete_node(node_id)

    def delete_edge(self, source: str, target: str, relationship: str = None) -> bool:
        """从知识图谱中删除边。"""
        return self.knowledge_graph.delete_edge(source, target, relationship)

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
        """保存所有记忆状态。"""
        # 保存热、温记忆
        self.basic_memory.save_to_file()
        
        # 保存冷记忆 (知识图谱)
        if self.graph_save_path:
            self.knowledge_graph.save_graph(self.graph_save_path)
        else:
            logger.warning("Knowledge graph save path is not set. Graph will not be saved.")
