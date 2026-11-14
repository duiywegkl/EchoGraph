"""Persistence checks for the memory adapter still used by the desktop graph."""

import json

import networkx as nx

from src.memory.grag_memory import GRAGMemory


def test_memory_rename_update_delete_persist(tmp_path):
    memory = GRAGMemory(
        graph_save_path=str(tmp_path / "graph.graphml"),
        entities_json_path=str(tmp_path / "entities.json"),
        auto_load_entities=False,
    )
    memory.add_or_update_node("A", "character")
    memory.add_or_update_node("B", "character")
    memory.add_edge("A", "B", "friend")
    assert memory.rename_node("A", "C")
    assert memory.update_edge("C", "B", "enemy", description="changed")
    memory.save_all_memory()
    entities = json.loads((tmp_path / "entities.json").read_text(encoding="utf-8"))
    graph = nx.read_graphml(tmp_path / "graph.graphml")
    assert {entity["name"] for entity in entities["entities"]} == {"B", "C"}
    assert graph.edges["C", "B"]["relationship"] == "enemy"
    assert entities["relationships"][0]["description"] == "changed"
    assert memory.delete_edge("C", "B")
    memory.save_all_memory()
    entities = json.loads((tmp_path / "entities.json").read_text(encoding="utf-8"))
    assert not nx.read_graphml(tmp_path / "graph.graphml").has_edge("C", "B")
    assert entities["relationships"] == []
