import json
import networkx as nx
import pytest

from src.graph.graph_operations import save_local_entities, clear_knowledge_graph


class FakeKnowledgeGraph:
    def __init__(self):
        self.graph = nx.Graph()

    def save_graph(self, path):
        nx.write_graphml(self.graph, path)

    def clear(self):
        self.graph.clear()


class FakeMemory:
    def __init__(self, root):
        self.knowledge_graph = FakeKnowledgeGraph()
        self.graph_save_path = str(root / "knowledge_graph.graphml")
        self.entities_json_path = root / "entities.json"

    def sync_entities_to_json(self):
        entities = [{"name": name, **attrs} for name, attrs in self.knowledge_graph.graph.nodes(data=True)]
        self.entities_json_path.write_text(json.dumps({"entities": entities}), encoding="utf-8")


def test_rename_preserves_edges_and_persists_both_files(tmp_path):
    memory = FakeMemory(tmp_path)
    graph = memory.knowledge_graph.graph
    graph.add_node("old", type="character")
    graph.add_node("friend", type="character")
    graph.add_edge("old", "friend", relationship="knows")
    save_local_entities(memory, [
        {"name": "new", "type": "character", "description": "updated"},
        {"name": "friend", "type": "character"},
    ], old_name="old", new_name="new")
    assert "old" not in graph
    assert graph.has_edge("new", "friend")
    assert graph["new"]["friend"]["relationship"] == "knows"
    assert nx.read_graphml(memory.graph_save_path).has_edge("new", "friend")
    assert {e["name"] for e in json.loads(memory.entities_json_path.read_text(encoding="utf-8"))["entities"]} == {"new", "friend"}


def test_delete_removes_node_and_incident_edges_from_both_files(tmp_path):
    memory = FakeMemory(tmp_path)
    graph = memory.knowledge_graph.graph
    graph.add_edge("removed", "kept")
    save_local_entities(memory, [{"name": "kept", "type": "concept"}])
    assert list(graph.nodes) == ["kept"]
    assert list(nx.read_graphml(memory.graph_save_path).nodes) == ["kept"]
    assert [e["name"] for e in json.loads(memory.entities_json_path.read_text(encoding="utf-8"))["entities"]] == ["kept"]


def test_duplicate_name_rejected_before_writing(tmp_path):
    memory = FakeMemory(tmp_path)
    with pytest.raises(ValueError):
        save_local_entities(memory, [{"name": "same"}, {"name": "same"}])
    assert not (tmp_path / "entities.json").exists()


def test_clear_keeps_non_graph_memory_and_clears_both_files(tmp_path):
    memory = FakeMemory(tmp_path)
    memory.basic_memory = {"conversation_history": ["keep"], "state_table": {"hp": 5}}
    memory.knowledge_graph.graph.add_edge("a", "b")
    clear_knowledge_graph(memory)
    assert memory.basic_memory == {"conversation_history": ["keep"], "state_table": {"hp": 5}}
    assert list(memory.knowledge_graph.graph.nodes) == []
    assert list(nx.read_graphml(memory.graph_save_path).nodes) == []
    assert json.loads(memory.entities_json_path.read_text(encoding="utf-8"))["entities"] == []


def test_edit_removes_deleted_dynamic_attributes(tmp_path):
    memory = FakeMemory(tmp_path)
    memory.knowledge_graph.graph.add_node("a", type="character", obsolete="old")
    save_local_entities(memory, [{"name": "a", "type": "character", "attributes": {"current": "new"}}])
    assert "obsolete" not in memory.knowledge_graph.graph.nodes["a"]
    assert memory.knowledge_graph.graph.nodes["a"]["current"] == "new"


def test_real_graph_save_surfaces_serialization_failure(tmp_path):
    from src.graph.knowledge_graph import KnowledgeGraph
    graph = KnowledgeGraph()
    graph.graph.add_node("a", unsupported={"nested": True})
    with pytest.raises(nx.NetworkXError):
        graph.save_graph(str(tmp_path / "bad.graphml"))
