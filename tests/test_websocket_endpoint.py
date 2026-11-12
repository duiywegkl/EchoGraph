from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_websocket_ping_with_existing_character_data(tmp_path, monkeypatch):
    session_id = "tavern_Test_12345678"
    current = tmp_path / "Test" / "sessions" / "current"
    current.mkdir(parents=True)
    (current / "existing.graphml").write_text("present", encoding="utf-8")
    storage = SimpleNamespace(
        active_sessions={}, character_mapping={"Test": "Test"},
        tavern_chars_path=tmp_path, _save_active_sessions=lambda: None,
    )
    loaded = Event()

    import src.storage
    monkeypatch.setattr(src.storage, "TavernStorageManager", lambda: storage)
    import api_server

    async def fake_auto_load(*args):
        assert args == (session_id, "Test", current)
        loaded.set()

    monkeypatch.setattr(api_server, "storage_manager", storage)
    monkeypatch.setattr(api_server, "manager", api_server.ConnectionManager())
    monkeypatch.setattr(api_server, "sessions", {})
    monkeypatch.setattr(api_server, "TAVERN_MODE_ACTIVE", True)
    monkeypatch.setattr(api_server, "auto_load_character_session", fake_auto_load)

    with TestClient(api_server.app) as client:
        with client.websocket_connect(f"/ws/tavern/{session_id}") as socket:
            assert socket.receive_json()["type"] == "connection_established"
            socket.send_json({"type": "request", "action": "ping", "request_id": "ping-1", "payload": {}})
            response = socket.receive_json()
            assert response == {
                "type": "response", "action": "ping", "request_id": "ping-1",
                "ok": True, "data": {"pong": True},
            }
    assert loaded.wait(1)
