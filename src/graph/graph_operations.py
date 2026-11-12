"""Persistence helpers shared by graph UI operations."""

import networkx as nx


def save_local_entities(memory, entities, old_name=None, new_name=None):
    """Update one local conversation graph and persist its two representations."""
    names = [entity["name"] for entity in entities]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate node names are not allowed")
    graph = memory.knowledge_graph.graph
    if old_name and new_name and old_name != new_name and old_name in graph:
        if new_name in graph:
            raise ValueError("A node with this name already exists")
        nx.relabel_nodes(graph, {old_name: new_name}, copy=False)
    wanted = set(names)
    for node in list(graph.nodes):
        if node not in wanted:
            graph.remove_node(node)
    for entity in entities:
        attributes = dict(entity.get("attributes", {}))
        attributes.update(type=entity.get("type", "concept"),
                          description=entity.get("description", ""))
        for key in ("created_time", "last_modified"):
            if key in entity:
                attributes[key] = entity[key]
        graph.add_node(entity["name"])
        graph.nodes[entity["name"]].clear()
        graph.nodes[entity["name"]].update(attributes)
    memory.sync_entities_to_json()
    memory.knowledge_graph.save_graph(memory.graph_save_path)


def clear_knowledge_graph(memory):
    """Clear graph storage without erasing conversation or warm memory."""
    memory.knowledge_graph.clear()
    memory.sync_entities_to_json()
    memory.knowledge_graph.save_graph(memory.graph_save_path)
