import asyncio


def test_plugin_status_reflects_recent_heartbeat(monkeypatch):
    import api_server
    from fastapi.testclient import TestClient

    now = [1000.0]
    monkeypatch.setattr(api_server.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(api_server, '_plugin_heartbeat_at', 0.0)
    monkeypatch.setattr(api_server, '_plugin_chat_uuid', None)
    api = TestClient(api_server.app)
    assert api.get('/system/plugin_status').json() == {'connected': False, 'chat_uuid': None}
    assert api.post('/timeline/heartbeat', json={'chat_uuid': 'chat-a'}).json() == {'ok': True}
    assert api.get('/system/plugin_status').json() == {'connected': True, 'chat_uuid': 'chat-a'}
    now[0] += 29.9
    assert api.get('/system/plugin_status').json()['connected']
    now[0] += 0.2
    assert api.get('/system/plugin_status').json() == {'connected': False, 'chat_uuid': None}
    assert api.post('/timeline/heartbeat', json={'chat_uuid': None}).status_code == 200
    assert api.get('/system/plugin_status').json() == {'connected': True, 'chat_uuid': None}
    assert api.post('/timeline/heartbeat', json={'chat_uuid': 123}).status_code == 400
