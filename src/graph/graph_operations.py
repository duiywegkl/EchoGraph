"""Persistence helpers shared by graph UI operations."""

import networkx as nx
from src.graph.node_types import TYPE_IDS, SYNONYMS, normalize_type


def save_local_entities(memory, entities, old_name=None, new_name=None):
    """Update one local conversation graph and persist its two representations."""
    for entity in entities:
        raw_type = entity.get("type", "other")
        if not isinstance(raw_type, str) or (raw_type not in TYPE_IDS and raw_type.strip().casefold() not in SYNONYMS):
            raise ValueError(f"Invalid node type: {raw_type}")
        entity["type"], subtype = normalize_type(raw_type, entity.get("subtype"))
        if subtype:
            entity["subtype"] = subtype
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
        attributes.update(type=entity.get("type", "other"),
                          subtype=entity.get("subtype", ""),
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


def save_local_relationship(memory, action, source, target, relationship=None):
    """Mutate one local conversation and persist entities.json plus GraphML."""
    graph = memory.knowledge_graph.graph
    if action == "create":
        if not graph.has_node(source) or not graph.has_node(target):
            raise ValueError("Both nodes must exist")
        if not relationship or not relationship.strip():
            raise ValueError("Relationship is required")
        # DiGraph stores one edge per ordered pair; create replaces its type.
        memory.add_edge(source, target, relationship.strip())
    elif action == "update":
        if not relationship or not relationship.strip():
            raise ValueError("Relationship is required")
        if not memory.update_edge(source, target, relationship.strip()):
            raise ValueError("Relationship does not exist")
    elif action == "delete":
        if not memory.delete_edge(source, target):
            raise ValueError("Relationship does not exist")
    else:
        raise ValueError("Unknown relationship action")
    memory.sync_entities_to_json()
    memory.knowledge_graph.save_graph(memory.graph_save_path)
