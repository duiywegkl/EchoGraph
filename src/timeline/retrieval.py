"""Bounded, attention-ranked prompt context for an effective timeline graph."""

import re

import networkx as nx

from src.graph.node_types import TYPE_LABELS
from src.memory.attention import DEFAULT_CONFIG, EntityImportanceEvaluator


def prompt_context(state, messages, limit):
    if not state.nodes:
        return ''
    limit = max(1, int(limit or 3000))
    recent_turns = max(1, min(limit // 200, 5))
    recent = [str(item.get('content') or '') for item in messages
              if item.get('included', True) and item.get('role') != 'lorebook'][-recent_turns:]
    text = '\n'.join(recent)
    graph = nx.MultiDiGraph()
    graph.add_nodes_from((ident, data) for ident, data in state.nodes.items())
    graph.add_edges_from((edge['source'], edge['target'], ident,
                          {'relationship': edge['relation']})
                         for ident, edge in state.edges.items())
    evaluator = EntityImportanceEvaluator(graph, text)

    def mentioned(ident, data):
        aliases = data.get('attributes', {}).get('aliases', [])
        if isinstance(aliases, str):
            aliases = [aliases]
        for name in (ident, data.get('name'), *aliases):
            if not name:
                continue
            pattern = rf'(?<!\w){re.escape(name)}(?!\w)' if name.isascii() else re.escape(name)
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    anchors = {ident for ident, data in state.nodes.items() if mentioned(ident, data)}
    candidates = set(anchors)
    for ident in anchors:
        candidates.update(graph.predecessors(ident))
        candidates.update(graph.successors(ident))
    if not candidates:
        candidates = set(state.nodes)
    slots = int(DEFAULT_CONFIG['max_context_entities'])
    ranked = sorted(candidates, key=lambda ident:
                    (ident not in anchors, -evaluator.score(ident)['importance_score'], ident))[:slots]
    selected = set(ranked)
    history = '\n'.join(recent)[-min(limit // 4, 600):]
    lines = ['## 最近对话', history, '', '## 相关知识图谱']
    for ident in ranked:
        node = state.nodes[ident]
        type_id = node.get('type', 'other')
        lines.append(f"{node.get('name', ident)} ({TYPE_LABELS.get(type_id, TYPE_LABELS['other'])}): {node.get('description', '')}")
    for edge in state.edges.values():
        if edge['source'] in selected and edge['target'] in selected:
            lines.append(f"{state.nodes[edge['source']]['name']} -> {state.nodes[edge['target']]['name']}: {edge['relation']}")
    return '\n'.join(lines)[:limit]
