import asyncio


def test_plugin_status_reflects_live_websockets(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server.manager, 'active_connections', {})
    assert asyncio.run(api_server.get_plugin_status()) == {'connected': False}
    api_server.manager.active_connections['tavern_active'] = {object()}
    assert asyncio.run(api_server.get_plugin_status()) == {'connected': True}
    api_server.manager.active_connections['tavern_active'].clear()
    assert asyncio.run(api_server.get_plugin_status()) == {'connected': False}


def test_multiple_tabs_receive_session_broadcast(monkeypatch):
    import api_server

    class Socket:
        def __init__(self):
            self.messages = []
            self.fail = False
            self.accepted = False

        async def accept(self):
            self.accepted = True

        async def send_json(self, message):
            if self.fail:
                raise RuntimeError("closed")
            self.messages.append(message)

    async def run():
        manager = api_server.ConnectionManager()
        first, second = Socket(), Socket()
        await manager.connect("test-session", first)
        await manager.connect("test-session", second)
        assert first.accepted and second.accepted
        await manager.send_message("test-session", {"type": "graph_updated"})
        assert len(first.messages) == len(second.messages) == 1
        first.fail = True
        await manager.send_message("test-session", {"type": "graph_updated"})
        assert manager.active_connections["test-session"] == {second}
        assert len(second.messages) == 2
        manager.disconnect("test-session", first)
        assert "test-session" in manager.active_connections
        manager.disconnect("test-session", second)
        assert "test-session" not in manager.active_connections
        assert await api_server._handle_ws_request("test-session", {"action": "ping"}) == {"ok": True, "data": {"pong": True}}

    asyncio.run(run())


def test_process_conversation_retries_are_idempotent(monkeypatch):
    import api_server

    calls = []

    async def process(req):
        calls.append(req.llm_response)
        return api_server.ProcessConversationResponse(
            message="ok", turn_sequence=len(calls), turn_processed=True,
            target_processed=False, window_size=1,
        )

    monkeypatch.setattr(api_server, "_process_conversation_impl", process)
    monkeypatch.setattr(api_server, "sessions", {"test-session": object()})
    api_server.processed_conversation_cache.clear()

    async def run():
        req = api_server.ProcessConversationRequest(
            session_id="test-session", user_input="hi", llm_response="one",
            tavern_message_id="m1", tavern_chat_id="chat-a",
        )
        first, retry = await asyncio.gather(
            api_server.process_conversation(req), api_server.process_conversation(req)
        )
        assert first.turn_sequence == retry.turn_sequence == 1
        changed = req.model_copy(update={"llm_response": "two"})
        assert (await api_server.process_conversation(changed)).turn_sequence == 2
        other_chat = req.model_copy(update={"tavern_chat_id": "chat-b"})
        assert (await api_server.process_conversation(other_chat)).turn_sequence == 3
        assert calls == ["one", "two", "one"]
        legacy = req.model_copy(update={"tavern_chat_id": None})
        await api_server.process_conversation(legacy)
        await api_server.process_conversation(legacy)
        assert calls == ["one", "two", "one", "one", "one"]

    asyncio.run(run())
    api_server.processed_conversation_cache.clear()
