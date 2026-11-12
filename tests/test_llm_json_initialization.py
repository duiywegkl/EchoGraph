import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.core.game_engine import GameEngine
from src.core.llm_client import ChatResult, LLMClient
from src.memory.grag_memory import GRAGMemory
from src.utils.llm_json import _parse, request_json, validate_kg


def kg(name='Hero', other='City'):
    return {'main_character': {'name': name, 'type': 'character', 'attributes': {}},
            'entities': [{'name': other, 'type': 'location', 'attributes': {}}],
            'relationships': [{'source': name, 'target': other, 'relationship': 'visits'}]}


class StubLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat_with_metadata(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def test_strict_fenced_and_local_repair():
    value = kg()
    assert _parse(json.dumps(value), validate_kg, False) == value
    assert _parse('Here is JSON:\n```json\n' + json.dumps(value) + '\n```', validate_kg, False) == value
    malformed = json.dumps(value).replace('"entities":', "'entities':")
    assert _parse(malformed, validate_kg, False)['entities'][0]['name'] == 'City'


def test_truncation_continues_and_malformed_repairs():
    raw = json.dumps(kg(), ensure_ascii=False)
    prefix = raw[:raw.index('City') + 2]
    llm = StubLLM([ChatResult(prefix, 'length'), ChatResult(raw[len(prefix):], 'stop')])
    parsed, rounds = request_json(llm, 'prompt', 'system', validate_kg)
    assert parsed == kg() and rounds == 1
    assert llm.calls[1][1]['json_mode'] is False
    malformed = '{"entities": [}'
    llm = StubLLM([ChatResult(malformed, 'stop'), ChatResult(raw, 'stop')])
    parsed, rounds = request_json(llm, 'prompt', 'system', validate_kg)
    assert parsed == kg() and rounds == 1
    assert llm.calls[1][1]['json_mode'] is True


def test_three_failed_rounds_and_api_exception():
    llm = StubLLM([ChatResult('x', 'stop')] * 4)
    with pytest.raises(ValueError, match='3 轮修复'):
        request_json(llm, 'prompt', 'system', validate_kg)
    assert len(llm.calls) == 4
    client = LLMClient.__new__(LLMClient)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_: (_ for _ in ()).throw(RuntimeError('API unavailable')))))
    client.model, client.max_tokens, client.temperature = 'stub', 100, 0.1
    with pytest.raises(RuntimeError, match='API unavailable'):
        client.chat([{'role': 'user', 'content': 'x'}])


def make_engine(tmp_path, responses):
    memory = GRAGMemory(graph_save_path=str(tmp_path / 'graph.graphml'),
                        entities_json_path=str(tmp_path / 'entities.json'), auto_load_entities=False)
    engine = GameEngine(memory, None, None, None, SimpleNamespace(llm_client=StubLLM(responses)))
    engine._is_llm_available = lambda: True
    return engine


def test_chunked_world_book_merges_and_bounds_prompts(tmp_path):
    entries = [f'Entry {i}: ' + ('A' * 1050) for i in range(25)]
    world = '\n\n'.join(entries)
    assert len(world) > 25000
    batches = GameEngine._world_batches(None, world)
    responses = [ChatResult(json.dumps(kg(other='Shared')), 'stop') for _ in range(len(batches) + 1)]
    engine = make_engine(tmp_path, responses)
    result = engine.initialize_from_tavern_data({'name': 'Hero', 'description': 'Main'}, world)
    assert result['method'] == 'llm_analysis'
    assert len(engine.grag_agent.llm_client.calls) == len(batches) + 1 > 2
    assert max(len(call[0][-1]['content']) for call in engine.grag_agent.llm_client.calls) < 8500
    assert len(engine.memory.knowledge_graph.graph.nodes()) == 2
    assert (tmp_path / 'graph.graphml').exists()


def test_one_batch_failure_is_partial(tmp_path):
    responses = [ChatResult(json.dumps(kg()), 'stop')] + [ChatResult('x', 'stop')] * 4
    engine = make_engine(tmp_path, responses)
    result = engine.initialize_from_tavern_data({'name': 'Hero'}, 'A world entry')
    assert result['method'] == 'partial' and '批次 2/2' in result['reason']
    assert len(engine.memory.knowledge_graph.graph.nodes()) == 2


def test_all_batches_fail_without_persisting_fallback(tmp_path):
    engine = make_engine(tmp_path, [ChatResult('x', 'stop')] * 4)
    with pytest.raises(RuntimeError, match='3 轮修复'):
        engine.initialize_from_tavern_data({'name': 'Hero'}, '')
    assert len(engine.memory.knowledge_graph.graph.nodes()) == 0
    assert not (tmp_path / 'graph.graphml').exists()
    assert not (tmp_path / 'entities.json').exists()


class RecordingOpenAI:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        content, finish = next(self.responses)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish)])


def recording_client(responses):
    provider = RecordingOpenAI(responses)
    client = LLMClient.__new__(LLMClient)
    client.client = provider
    client.model = 'stub'
    client.temperature = 0.1
    return client, provider


def test_openai_initialization_all_batches_have_no_output_cap(tmp_path):
    entries = [f'Entry {i}: ' + 'A' * 1050 for i in range(18)]
    world = '\n\n'.join(entries)
    batches = GameEngine._world_batches(None, world)
    client, provider = recording_client(
        [(json.dumps(kg(other='Shared')), 'stop')] * (len(batches) + 1))
    memory = GRAGMemory(graph_save_path=str(tmp_path / 'graph.graphml'),
                        entities_json_path=str(tmp_path / 'entities.json'),
                        auto_load_entities=False)
    engine = GameEngine(memory, None, None, None, SimpleNamespace(llm_client=client))
    engine._is_llm_available = lambda: True
    engine.initialize_from_tavern_data({'name': 'Hero'}, world)
    assert len(provider.requests) == len(batches) + 1 > 2
    assert all('max_tokens' not in request for request in provider.requests)


def test_openai_continuation_repair_and_grag_update_have_no_output_cap():
    raw = json.dumps(kg())
    prefix = raw[:raw.index('City') + 2]
    client, provider = recording_client([
        (prefix, 'length'), (raw[len(prefix):], 'stop'),
        ('{"entities": [}', 'stop'), (raw, 'stop'),
        ('{"operations": []}', 'stop'),
    ])
    assert request_json(client, 'prompt', 'system', validate_kg)[0] == kg()
    assert request_json(client, 'prompt', 'system', validate_kg)[0] == kg()
    from src.core.grag_update_agent import GRAGUpdateAgent
    from src.graph.knowledge_graph import KnowledgeGraph
    result = GRAGUpdateAgent(client).analyze_conversation_for_updates(
        'hello', 'reply', KnowledgeGraph())
    assert result['operations'] == []
    assert len(provider.requests) == 5
    assert [request.get('response_format') for request in provider.requests] == [
        {'type': 'json_object'}, None, {'type': 'json_object'},
        {'type': 'json_object'}, {'type': 'json_object'}]
    assert all('max_tokens' not in request for request in provider.requests)


def test_reply_uses_reloaded_max_tokens(tmp_path, monkeypatch):
    from src.utils import config as config_module
    import src.core.llm_client as llm_module
    from src.ui.workers.llm_worker import LLMWorkerThread

    env_path = tmp_path / '.env'
    original_env_path = config_module.env_file
    monkeypatch.setattr(config_module, 'env_file', env_path)
    monkeypatch.setattr(config_module, '_loaded_env_keys', set())
    provider = RecordingOpenAI([('first', 'stop'), ('second', 'stop')])
    monkeypatch.setattr(llm_module.openai, 'OpenAI', lambda **kwargs: provider)
    engine = SimpleNamespace(
        perception=SimpleNamespace(analyze=lambda *_: {'entities': []}),
        memory=SimpleNamespace(
            knowledge_graph=object(),
            retrieve_context_for_prompt=lambda *_args, **_kwargs: 'context'))
    try:
        env_path.write_text('OPENAI_API_KEY=fake\nMAX_TOKENS=1234\n', encoding='utf-8')
        config_module.reload_config(env_path)
        worker = LLMWorkerThread(engine, 'hi')
        errors = []
        worker.error_occurred.connect(errors.append)
        worker.run()
        assert not errors
        assert provider.requests[0]['max_tokens'] == config_module.config.llm.max_tokens == 1234

        env_path.write_text('OPENAI_API_KEY=fake\nMAX_TOKENS=4321\n', encoding='utf-8')
        config_module.reload_config(env_path)
        worker.run()
        assert not errors
        assert provider.requests[1]['max_tokens'] == config_module.config.llm.max_tokens == 4321
    finally:
        monkeypatch.setattr(config_module, 'env_file', original_env_path)
        monkeypatch.setattr(config_module, '_loaded_env_keys', set())
        config_module.reload_config()


def test_openai_client_only_sends_explicit_positive_integer_cap():
    client, provider = recording_client([('ok', 'stop')] * 5)
    for cap in (None, 0, -1, True):
        assert client.generate_response('prompt', max_tokens=cap) == 'ok'
    assert client.chat([{'role': 'user', 'content': 'hello'}], max_tokens=567) == 'ok'
    assert all('max_tokens' not in request for request in provider.requests[:4])
    assert provider.requests[4]['max_tokens'] == 567
