import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.core.llm_client import ChatResult, LLMClient
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
            knowledge_graph=SimpleNamespace(graph=SimpleNamespace(nodes=[])),
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
