"""Deterministic importance scores for graph entities."""

import re


ENTITY_TYPE_WEIGHTS = {
    'character': 1.0, 'location': 0.8, 'item': 0.7,
    'event': 0.6, 'concept': 0.4,
}
RELATIONSHIP_WEIGHTS = {
    'owns': 0.8, 'controls': 0.9, 'manages': 0.8, 'created': 0.7,
    'located_in': 0.6, 'uses': 0.5, 'follows': 0.3,
    'develops': 0.4, 'implements': 0.4, 'plans': 0.2, 'supports': 0.3,
    '拥有': 0.8, '控制': 0.9, '管理': 0.8, '创建': 0.7,
    '位于': 0.6, '使用': 0.5, '遵循': 0.3, '研发': 0.4,
    '实施': 0.4, '计划': 0.2, '支持': 0.3,
}
DEFAULT_CONFIG = {
    'collective_weight': 0.6,
    'holistic_weight': 0.4,
    'importance_threshold': 0.3,
    'max_context_entities': 15,
}


class EntityImportanceEvaluator:
    """Score entities using recent text and the original directed graph."""

    def __init__(self, graph, conversation_text='', config=None):
        self.graph = graph
        self.conversation_text = conversation_text or ''
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    def collective_score(self, entity_id):
        attrs = self.graph.nodes[entity_id]
        aliases = attrs.get('aliases', [])
        if isinstance(aliases, str):
            aliases = [aliases]
        names = {str(name).strip().casefold() for name in [entity_id, attrs.get('name'), *aliases] if name}
        text = self.conversation_text.casefold()
        counts = []
        for name in names:
            # Bound Latin names to words while allowing Chinese names inside sentences.
            pattern = rf'(?<!\w){re.escape(name)}(?!\w)' if name.isascii() else re.escape(name)
            counts.append(len(re.findall(pattern, text)))
        mentions = max(counts, default=0)  # aliases of the same mention do not double count
        return mentions / (mentions + 1) if mentions else 0.0

    def holistic_score(self, entity_id):
        attrs = self.graph.nodes[entity_id]
        entity_weight = ENTITY_TYPE_WEIGHTS.get(str(attrs.get('type', '')).lower(), 0.5)
        edges = list(self.graph.in_edges(entity_id, data=True)) + list(self.graph.out_edges(entity_id, data=True))
        weights = [RELATIONSHIP_WEIGHTS.get(str(data.get('relationship', '')).lower(), 0.3)
                   for _, _, data in edges]
        relationship_weight = sum(weights) / len(weights) if weights else 0.0
        degree_weight = len(edges) / (len(edges) + 3) if edges else 0.0
        return 0.6 * entity_weight + 0.25 * relationship_weight + 0.15 * degree_weight

    def score(self, entity_id):
        collective = self.collective_score(entity_id)
        holistic = self.holistic_score(entity_id)
        importance = (self.config['collective_weight'] * collective +
                      self.config['holistic_weight'] * holistic)
        return {
            'name': entity_id,
            'type': self.graph.nodes[entity_id].get('type', 'unknown'),
            'collective_score': collective,
            'holistic_score': holistic,
            'importance_score': max(0.0, min(1.0, importance)),
        }
