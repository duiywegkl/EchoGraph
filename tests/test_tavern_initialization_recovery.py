import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api_server
from src.storage.tavern_storage_manager import TavernStorageManager


class Graph:
    def __init__(self):
        self._nodes = []
        self._edges = []

    def nodes(self):
        return self._nodes

    def edges(self):
        return self._edges


class Engine:
    def __init__(self):
        self.graph = Graph()
        self.memory = SimpleNamespace(
            knowledge_graph=SimpleNamespace(graph=self.graph),
            sync_entities_to_json=lambda: None,
        )
        self.grag_agent = object()
        self._llm_settings = (
            api_server.config.llm.api_key,
            api_server.config.llm.base_url,
            api_server.config.llm.model,
        )
        self.calls = 0
        self.outcome = "nodes"

    def initialize_from_tavern_data(self, card, world):
        self.calls += 1
        if self.outcome == "failure":
            raise RuntimeError("stub extraction failed")
        if self.outcome == "partial_failure":
            self.graph.nodes().append("partial")
            raise RuntimeError("partial extraction failed")
        if self.outcome == "nodes":
            self.graph.nodes().append(card["name"])
            return {"nodes_added": 1, "edges_added": 0}
        return {"nodes_added": 0, "edges_added": 0, "reason": "LLM returned no entities"}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    storage = TavernStorageManager(str(tmp_path / "storage"))
    monkeypatch.setattr(api_server, "storage_manager", storage)
    monkeypatch.setattr(api_server, "sessions", {})
    monkeypatch.setattr(api_server, "manager", api_server.ConnectionManager())
    monkeypatch.setattr(api_server, "TAVERN_MODE_ACTIVE", True)
    monkeypatch.setattr(api_server, "plugin_character_data", {})
    monkeypatch.setattr(api_server, "pending_coordinated_reinits", set())
    monkeypatch.setattr(api_server, "initializing_sessions", set())
    engine = Engine()
    sid = "tavern_Test_12345678"
    card = {"name": "Test", "description": "A character and a city"}
    storage.register_tavern_character(card, sid)
    api_server.sessions[sid] = engine
    monkeypatch.setattr(api_server, "get_or_create_session_engine", lambda *_: engine)
    return storage, engine, sid, card


def ws_request(socket, action, payload=None):
    socket.send_json({
        "type": "request", "action": action, "request_id": action,
        "payload": payload or {},
    })
    while True:
        response = socket.receive_json()
        if response.get("type") == "response" and response.get("request_id") == action:
            return response


def test_leftover_empty_session_plugin_flow_extracts(isolated):
    storage, engine, sid, card = isolated
    with TestClient(api_server.app) as client:
        with client.websocket_connect(f"/ws/tavern/{sid}") as socket:
            assert socket.receive_json()["type"] == "connection_established"
            current = ws_request(socket, "tavern.current_session")["data"]
            assert current["has_session"] and current["graph_nodes"] == 0
            assert current["needs_initialization"]
            submitted = ws_request(socket, "tavern.submit_character", {
                "character_id": "0", "character_name": "Test", "character_data": card,
            })
            assert submitted["ok"]
            initialized = ws_request(socket, "initialize", {
                "session_id": sid, "character_card": card, "world_info": "A city",
                "is_test": False,
            })
            assert initialized["ok"], initialized
            assert initialized["data"]["graph_stats"]["nodes_added"] == 1
            assert engine.calls == 1
            after = ws_request(socket, "tavern.current_session")["data"]
            assert after["graph_nodes"] == 1 and not after["needs_initialization"]
    assert storage.active_sessions[sid]["initialization_status"] == "completed"


def test_nonempty_session_skips_extraction(isolated):
    _, engine, sid, card = isolated
    engine.graph.nodes().append("preserved")
    api_server._set_initialization_state(sid, "completed")
    with TestClient(api_server.app) as client:
        response = client.post("/initialize", json={
            "session_id": sid, "character_card": card, "world_info": "",
        })
    assert response.status_code == 200
    assert response.json()["graph_stats"]["nodes_added"] == 1
    assert engine.calls == 0
    assert engine.graph.nodes() == ["preserved"]


def test_failed_initialization_is_retryable(isolated):
    storage, engine, sid, card = isolated
    engine.outcome = "failure"
    with TestClient(api_server.app) as client:
        payload = {"session_id": sid, "character_card": card, "world_info": ""}
        failed = client.post("/initialize", json=payload)
        assert failed.status_code == 500
        state = client.get("/tavern/current_session").json()
        assert state["initialization_status"] == "failed"
        assert state["needs_initialization"]
        assert "stub extraction failed" in state["initialization_reason"]
        engine.outcome = "nodes"
        retried = client.post("/initialize", json=payload)
        assert retried.status_code == 200
        assert retried.json()["graph_stats"]["nodes_added"] == 1
    assert engine.calls == 2
    assert storage.active_sessions[sid]["initialization_status"] == "completed"


def test_empty_completed_extraction_does_not_loop(isolated):
    storage, engine, sid, card = isolated
    engine.outcome = "empty"
    with TestClient(api_server.app) as client:
        payload = {"session_id": sid, "character_card": card, "world_info": ""}
        first = client.post("/initialize", json=payload)
        assert first.status_code == 200
        assert "角色卡未提取到实体" in first.json()["message"]
        state = client.get("/tavern/current_session").json()
        assert state["has_session"] and state["graph_nodes"] == 0
        assert not state["needs_initialization"]
        assert "LLM returned no entities" in state["initialization_reason"]
        second = client.post("/initialize", json=payload)
        assert second.status_code == 200
    assert engine.calls == 1
    assert storage.active_sessions[sid]["initialization_status"] == "completed"


def test_autoload_notifies_every_socket(isolated, tmp_path, monkeypatch):
    storage, _, sid, _ = isolated
    import src.core.game_engine
    import src.memory.grag_memory
    import src.core.perception
    import src.core.rpg_text_processor
    import src.core.validation

    loaded_graph = Graph()
    loaded_graph.nodes().append("saved")
    memory = SimpleNamespace(knowledge_graph=SimpleNamespace(graph=loaded_graph))
    monkeypatch.setattr(src.memory.grag_memory, "GRAGMemory", lambda **_: memory)
    for module, name in (
        (src.core.perception, "PerceptionModule"),
        (src.core.rpg_text_processor, "RPGTextProcessor"),
        (src.core.validation, "ValidationLayer"),
    ):
        monkeypatch.setattr(module, name, lambda: object())
    monkeypatch.setattr(api_server, "build_grag_agent_or_raise", lambda: object())
    monkeypatch.setattr(src.core.game_engine, "GameEngine",
                        lambda *args: SimpleNamespace(memory=memory))
    api_server.sessions.clear()
    path = tmp_path / "stored"
    path.mkdir()

    class Socket:
        def __init__(self):
            self.messages = []

        async def accept(self):
            pass

        async def send_json(self, message):
            self.messages.append(message)

    async def run():
        a, b = Socket(), Socket()
        await api_server.manager.connect(sid, a)
        await api_server.manager.connect(sid, b)
        await api_server.auto_load_character_session(sid, "Test", path)
        return a, b

    first, second = asyncio.run(run())
    assert first.messages[0]["type"] == second.messages[0]["type"] == "session_loaded"
    assert first.messages[0]["graph_nodes"] == second.messages[0]["graph_nodes"] == 1
    assert storage.active_sessions[sid]["status"] == "loaded"



def test_partial_failure_rolls_back_nodes_and_retries(isolated):
    storage, engine, sid, card = isolated
    engine.outcome = "partial_failure"
    with TestClient(api_server.app) as client:
        payload = {"session_id": sid, "character_card": card, "world_info": ""}
        assert client.post("/initialize", json=payload).status_code == 500
        assert engine.graph.nodes() == []
        state = client.get("/tavern/current_session").json()
        assert state["graph_nodes"] == 0
        assert state["initialization_status"] == "failed"
        assert state["needs_initialization"]
        engine.outcome = "nodes"
        assert client.post("/initialize", json=payload).status_code == 200
    assert engine.graph.nodes() == ["Test"]
    assert engine.calls == 2
    assert storage.active_sessions[sid]["initialization_status"] == "completed"


def test_interrupted_initialization_is_retryable(isolated):
    storage, engine, sid, _ = isolated
    engine.graph.nodes().append("partial")
    storage.active_sessions[sid]["initialization_status"] = "initializing"
    state = api_server._initialization_state(sid, 1)
    assert state["initialization_status"] == "failed"
    assert state["needs_initialization"]
    assert "中断" in state["initialization_reason"]



def test_engine_creation_failure_after_registration_is_retryable(isolated, monkeypatch):
    storage, engine, sid, card = isolated
    api_server.sessions.clear()

    def missing_key(*_):
        raise RuntimeError("LLM API Key 未配置")

    monkeypatch.setattr(api_server, "get_or_create_session_engine", missing_key)
    with TestClient(api_server.app) as client:
        payload = {"session_id": sid, "character_card": card, "world_info": ""}
        failed = client.post("/initialize", json=payload)
        assert failed.status_code == 500
        state = client.get("/tavern/current_session").json()
        assert state["has_session"] and state["needs_initialization"]
        assert state["initialization_status"] == "failed"
        assert "Key" in state["initialization_reason"]
        assert storage.active_sessions[sid]["initialization_status"] == "failed"
        monkeypatch.setattr(api_server, "get_or_create_session_engine",
                            lambda *_: api_server.sessions.setdefault(sid, engine))
        retried = client.post("/initialize", json=payload)
        assert retried.status_code == 200
    assert engine.calls == 1


def test_websocket_failure_contains_backend_reason(isolated):
    _, engine, sid, card = isolated
    engine.outcome = "failure"
    with TestClient(api_server.app) as client:
        with client.websocket_connect(f"/ws/tavern/{sid}") as socket:
            assert socket.receive_json()["type"] == "connection_established"
            response = ws_request(socket, "initialize", {
                "session_id": sid, "character_card": card, "world_info": "",
            })
            assert not response["ok"]
            assert response["error"]["code"] == 500
            assert "stub extraction failed" in response["error"]["message"]


def test_concurrent_initialize_shares_result(isolated):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import time
    storage, engine, sid, card = isolated
    entered = Event()
    release = Event()
    original = engine.initialize_from_tavern_data

    def slow_initialize(card, world):
        entered.set()
        assert release.wait(5)
        return original(card, world)

    engine.initialize_from_tavern_data = slow_initialize
    payload = {"session_id": sid, "character_card": card, "world_info": ""}
    with TestClient(api_server.app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, '/initialize', json=payload)
        assert entered.wait(5)
        second = pool.submit(client.post, '/initialize', json=payload)
        time.sleep(0.1)
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert engine.calls == 1
    assert storage.active_sessions[sid]['initialization_status'] == 'completed'


def test_failed_initialization_restores_disk(isolated, tmp_path):
    storage, engine, sid, card = isolated
    graph_path = tmp_path / 'graph.graphml'
    entities_path = tmp_path / 'entities.json'
    graph_path.write_text('original graph', encoding='utf-8')
    entities_path.write_text('original entities', encoding='utf-8')
    engine.memory.graph_save_path = str(graph_path)
    engine.memory.entities_json_path = str(entities_path)

    def fail_after_writing(card, world):
        engine.graph.nodes().append('fallback')
        graph_path.write_text('fallback graph', encoding='utf-8')
        entities_path.write_text('fallback entities', encoding='utf-8')
        raise RuntimeError('3 轮修复仍无法解析')

    engine.initialize_from_tavern_data = fail_after_writing
    with TestClient(api_server.app) as client:
        failed = client.post('/initialize', json={
            'session_id': sid, 'character_card': card, 'world_info': ''})
        assert failed.status_code == 500
        state = client.get('/tavern/current_session').json()
    assert '3 轮修复' in state['initialization_reason']
    assert state['initialization_status'] == 'failed'
    assert engine.graph.nodes() == []
    assert graph_path.read_text(encoding='utf-8') == 'original graph'
    assert entities_path.read_text(encoding='utf-8') == 'original entities'


def test_partial_status_and_reason_visible(isolated):
    storage, engine, sid, card = isolated

    def partial(card, world):
        engine.calls += 1
        engine.graph.nodes().append(card['name'])
        return {'nodes_added': 1, 'edges_added': 0, 'method': 'partial',
                'reason': '批次 2/3: JSON 修复 3 轮失败'}

    engine.initialize_from_tavern_data = partial
    with TestClient(api_server.app) as client:
        payload = {'session_id': sid, 'character_card': card, 'world_info': 'world'}
        first = client.post('/initialize', json=payload)
        assert first.status_code == 200
        assert '批次 2/3' in first.json()['message']
        state = client.get('/tavern/current_session').json()
        assert state['initialization_status'] == 'partial'
        assert 'JSON 修复' in state['initialization_reason']
        second = client.post('/initialize', json=payload)
        assert second.status_code == 200
        assert '批次 2/3' in second.json()['message']
    assert engine.calls == 1
