import json
from types import SimpleNamespace

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from src.memory.grag_memory import GRAGMemory
from src.graph.graph_operations import save_local_relationship


@pytest.fixture
def memory(tmp_path):
    return GRAGMemory(graph_save_path=str(tmp_path / "graph.graphml"),
                      entities_json_path=str(tmp_path / "entities.json"),
                      auto_load_entities=False)


def saved(memory):
    return json.loads(open(memory.entities_json_path, encoding="utf-8").read()), nx.read_graphml(memory.graph_save_path)


def test_memory_rename_update_delete_persist(memory):
    memory.add_or_update_node("A", "character")
    memory.add_or_update_node("B", "character")
    memory.add_edge("A", "B", "friend")
    assert memory.rename_node("A", "C")
    assert memory.update_edge("C", "B", "enemy", description="changed")
    memory.save_all_memory()
    entities, graph = saved(memory)
    assert {e["name"] for e in entities["entities"]} == {"B", "C"}
    assert graph.edges["C", "B"]["relationship"] == "enemy"
    assert entities["relationships"][0]["description"] == "changed"
    assert memory.delete_edge("C", "B")
    memory.save_all_memory()
    entities, graph = saved(memory)
    assert not graph.has_edge("C", "B")
    assert entities["relationships"] == []


def test_local_relationship_path(memory):
    memory.add_or_update_node("A", "character")
    memory.add_or_update_node("B", "character")
    for action, value in (("create", "friend"), ("update", "enemy"), ("delete", None)):
        save_local_relationship(memory, action, "A", "B", value)
        entities, graph = saved(memory)
        assert graph.has_edge("A", "B") == (action != "delete")
        assert len(entities["relationships"]) == (action != "delete")
        if value:
            assert graph.edges["A", "B"]["relationship"] == value


@pytest.fixture
def api(memory, monkeypatch):
    import api_server
    events = []
    async def send(session_id, payload):
        events.append((session_id, payload))
    monkeypatch.setattr(api_server.manager, "send_message", send)
    monkeypatch.setattr(api_server, "sessions", {"test-session": SimpleNamespace(memory=memory)})
    return TestClient(api_server.app), events


def test_api_mutations_and_broadcast(api):
    client, events = api
    prefix = "/sessions/test-session"
    for name in ("A", "B"):
        assert client.post(prefix + "/nodes", json={"name": name, "type": "character"}).status_code == 200
    assert client.post(prefix + "/nodes", json={"name": "A", "type": "character"}).status_code == 409
    assert client.post(prefix + "/nodes", json={"name": "", "type": "character"}).status_code == 400
    assert client.post("/sessions/missing/nodes", json={"name": "X", "type": "character"}).status_code == 404
    assert client.put(prefix + "/nodes/A", json={"name": "C", "type": "character"}).status_code == 200
    assert client.put(prefix + "/nodes/C", json={"name": "B"}).status_code == 409
    assert client.put(prefix + "/nodes/missing", json={"name": "X"}).status_code == 404
    assert client.put(prefix + "/nodes/C", json={"name": ""}).status_code == 400
    rel = {"source": "C", "target": "B", "relationship": "friend"}
    assert client.post(prefix + "/relationships", json=rel).status_code == 200
    assert client.post(prefix + "/relationships", json={**rel, "relationship": "ally"}).status_code == 200
    assert client.put(prefix + "/relationships", json={**rel, "relationship": "enemy"}).status_code == 200
    assert client.put(prefix + "/relationships", json={"source": "B", "target": "C", "relationship": "x"}).status_code == 404
    assert client.put(prefix + "/relationships", json={"source": "C", "target": "B"}).status_code == 400
    assert client.post(prefix + "/relationships", json={"source": "C", "target": "X", "relationship": "x"}).status_code == 404
    assert client.post(prefix + "/relationships", json={"source": "C", "target": "B"}).status_code == 400
    assert client.delete(prefix + "/relationships", params={"source": "C", "target": "B"}).status_code == 200
    assert client.delete(prefix + "/relationships", params={"source": "C", "target": "B"}).status_code == 404
    assert client.delete(prefix + "/relationships", params={"source": "" , "target": "B"}).status_code == 400
    assert client.delete(prefix + "/nodes/B").status_code == 200
    assert [p["action"] for _, p in events] == [
        "node_created", "node_created", "node_updated", "relationship_created",
        "relationship_created", "relationship_updated", "relationship_deleted", "node_deleted"]
    assert all(p["source"] == "manual_edit" and "total_edges" in p for _, p in events)
    assert events[-1][1]["total_nodes"] == 1


def test_broadcast_failure_does_not_fail_mutation(api, monkeypatch):
    import api_server
    client, _ = api
    async def fail(*args):
        raise RuntimeError("socket closed")
    monkeypatch.setattr(api_server.manager, "send_message", fail)
    response = client.post("/sessions/test-session/nodes", json={"name": "A", "type": "character"})
    assert response.status_code == 200


def test_failed_rename_returns_500_without_update_or_broadcast(api, memory, monkeypatch):
    client, events = api
    memory.add_or_update_node("A", "character")
    monkeypatch.setattr(memory, "rename_node", lambda old, new: False)
    updated = []
    monkeypatch.setattr(memory, "add_or_update_node", lambda *args, **kwargs: updated.append(args))

    response = client.put("/sessions/test-session/nodes/A", json={"name": "B", "type": "character"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to rename node 'A' to 'B'"
    assert not updated
    assert not events
    assert list(memory.knowledge_graph.graph.nodes) == ["A"]
