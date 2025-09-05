import re
from typing import Dict, Any, List

from src.graph import KnowledgeGraph

class PerceptionModule:
    """
    感知模块，负责解析用户输入，提取实体和意图。
    当前版本不依赖LLM，使用基于规则和知识图谱的方法。
    """

    def __init__(self):
        # 简单的意图识别规则 (中英双语)
        self.intent_keywords = {
            "question": ["who", "what", "where", "when", "why", "how", "?", "什么", "谁", "哪里", "为什么", "怎样", "吗"],
            "action": ["go to", "pick up", "talk to", "attack", "use", "去", "前往", "捡起", "对话", "攻击", "使用"],
            "describe": ["look at", "describe", "check", "观察", "查看", "描述"],
        }

    def analyze(self, text: str, kg: KnowledgeGraph) -> Dict[str, Any]:
        """
        分析给定的文本，提取实体和意图。
        此版本支持中文实体别名搜索。

        Args:
            text (str): 用户的输入文本。
            kg (KnowledgeGraph): 当前的知识图谱，用于实体链接。

        Returns:
            Dict[str, Any]: 一个包含分析结果的结构化字典。
        """
        normalized_text = text.lower().strip()
        
        # 1. 实体提取 (Entity Extraction)
        extracted_entities = []
        # 创建一个包含所有待搜索名称的列表 (ID, name, aliases)
        search_candidates = []
        for node_id, attrs in kg.graph.nodes(data=True):
            # 1. 添加节点ID本身
            search_candidates.append((node_id, node_id))
            # 2. 添加name属性
            if attrs.get('name'):
                search_candidates.append((attrs.get('name'), node_id))
            # 3. 添加aliases列表中的所有别名
            if attrs.get('aliases'):
                for alias in attrs.get('aliases'):
                    search_candidates.append((alias, node_id))
        
        # 按名称长度降序排序，优先匹配更长的实体名 (e.g., "elara's shop" vs "elara")
        search_candidates.sort(key=lambda x: len(x[0]), reverse=True)

        temp_text = normalized_text
        for name, node_id in search_candidates:
            # 如果在文本中找到了实体名称
            if name.lower() in temp_text:
                # 将找到的实体ID加入结果列表 (确保不重复)
                if node_id not in extracted_entities:
                    extracted_entities.append(node_id)
                # 从文本中移除已找到的实体名，避免子字符串重复匹配
                # 例如，找到 "elara's shop" 后，将其移除，以免再次匹配到 "elara"
                temp_text = temp_text.replace(name.lower(), "")

        # 2. 意图分析 (Intent Analysis)
        detected_intent = "unknown"
        for intent, keywords in self.intent_keywords.items():
            if any(keyword in normalized_text for keyword in keywords):
                detected_intent = intent
                break
        
        if detected_intent == "unknown" and extracted_entities:
            detected_intent = "dialogue"

        return {
            "raw_text": text,
            "normalized_text": normalized_text,
            "entities": extracted_entities,
            "intent": detected_intent,
        }
