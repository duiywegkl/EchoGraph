import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.utils import config as config_module
from src.utils.model_catalog import context_size, fetch_models, model_details, parse_models, validate_endpoint


def test_timeline_config_reload(temporary_config):
    temporary_config.write_text('LLM_CONTEXT_SIZE=64000\nTIMELINE_PER_TURN_REGEN=true\n'
                                'TIMELINE_INCLUDE_GLOBAL_PERSONA_BOOKS=true\n', encoding='utf-8')
    config_module.reload_config()
    assert config_module.config.llm.context_size == 64000
    assert config_module.config.timeline.per_turn_regen
    assert config_module.config.timeline.include_global_persona_books
    assert context_size({'context_length': 128000, 'max_input_tokens': 64000}) == (128000, '上下文长度')
    assert context_size({'max_input_tokens': 64000}) == (64000, '仅最大输入 tokens')


@pytest.fixture
def temporary_config(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    original = config_module.env_file
    monkeypatch.setattr(config_module, "env_file", path)
    monkeypatch.setattr(config_module, "_loaded_env_keys", set())
    yield path
    monkeypatch.setattr(config_module, "env_file", original)
    monkeypatch.setattr(config_module, "_loaded_env_keys", set())
    config_module.reload_config()


def test_reload_file_wins_and_updates_singleton(temporary_config, monkeypatch):
    from src.utils.config import config as imported_config
    old_id, old_llm_id = id(imported_config), id(imported_config.llm)
    monkeypatch.setenv("OPENAI_API_KEY", "inherited-stale")
    monkeypatch.setenv("OPENAI_API_BASE_URL", "http://stale.example")
    temporary_config.write_text("OPENAI_API_KEY=file-key\nOPENAI_API_BASE_URL=http://file.example/v1\nDEFAULT_MODEL=file-model\n", encoding="utf-8")
    config_module.reload_config()
    assert id(imported_config) == old_id
    assert id(imported_config.llm) == old_llm_id
    assert imported_config.llm.api_key == os.environ["OPENAI_API_KEY"] == "file-key"
    assert imported_config.llm.base_url == "http://file.example/v1"
    assert imported_config.llm.model == "file-model"


def test_retired_environment_keys_are_ignored(temporary_config):
    temporary_config.write_text(
        "SLIDING_WINDOW_SIZE=invalid\nPROCESSING_DELAY=invalid\n"
        "ENABLE_CONFLICT_RESOLUTION=true\nTIMELINE_PER_TURN_REGEN=true\n",
        encoding="utf-8",
    )
    config_module.reload_config()
    assert config_module.config.timeline.per_turn_regen
    assert not hasattr(config_module.config.game, "sliding_window_size")






def test_backend_reload_localhost_only(temporary_config):
    import api_server

    temporary_config.write_text("OPENAI_API_KEY=secret-test-key\n", encoding="utf-8")
    with TestClient(api_server.app, client=("203.0.113.7", 12345)) as client:
        result = client.post("/system/reload_config")
        assert result.status_code == 403
        assert "secret-test-key" not in result.text


def test_backend_never_echoes_key_embedded_in_url(temporary_config):
    import api_server

    temporary_config.write_text("OPENAI_API_KEY=secret-test-key\nOPENAI_API_BASE_URL=http://fake.example/secret-test-key\n", encoding="utf-8")
    with TestClient(api_server.app, client=("::1", 12345)) as client:
        result = client.post("/system/reload_config")
        assert result.status_code == 200
        assert "secret-test-key" not in result.text
        assert result.json()["base_url"] == "http://fake.example/***"


@pytest.mark.parametrize("payload, expected", [
    ({"data": [{"id": "z"}, {"id": "a"}]}, ["a", "z"]),
    ([{"id": "bare"}], ["bare"]),
])
def test_parse_models(payload, expected):
    assert list(parse_models(payload)) == expected


def test_metadata_shapes():
    openrouter = {"id": "or", "context_length": 128000,
                  "top_provider": {"max_completion_tokens": 8192},
                  "architecture": {"input_modalities": ["text", "image"]},
                  "supported_parameters": ["tools", "reasoning", "response_format"],
                  "pricing": {"prompt": "0.001", "completion": "0.002"}, "owned_by": "provider"}
    details = model_details(openrouter)
    assert details["上下文长度"] == "128000"
    assert details["最大输出"] == "8192"
    assert details["图片输入"] == details["工具调用"] == details["推理"] == "支持"
    assert details["JSON/结构化输出"] == "支持"
    assert "0.001" in details["价格"]
    capabilities = model_details({"capabilities": {"vision": True, "function_calling": False, "reasoning": True}})
    assert capabilities["图片输入"] == "支持"
    assert capabilities["工具调用"] == "不支持"
    assert capabilities["推理"] == "支持"


def test_model_errors_and_retry(monkeypatch):
    from src.utils import model_catalog

    for url, key, message in [("", "k", "接口地址"), ("https://example.test", "", "密钥"),
                              ("example.test", "k", "无效")]:
        with pytest.raises(ValueError, match=message):
            validate_endpoint(url, key)
    with pytest.raises(ValueError, match="格式无效"):
        parse_models({"data": {}})
    with pytest.raises(ValueError, match="为空"):
        parse_models({"data": []})

    seen = []

    def fake_get(url, **kwargs):
        seen.append(url)
        assert kwargs["headers"]["Authorization"] == "Bearer fake-key"
        if url.endswith("/v1/models"):
            return SimpleNamespace(status_code=200, ok=True, json=lambda: {"data": [{"id": "fallback"}]})
        return SimpleNamespace(status_code=404, ok=False)

    monkeypatch.setattr(model_catalog.requests, "get", fake_get)
    models, retried = fetch_models("http://fake.test", "fake-key", 2)
    assert list(models) == ["fallback"] and retried
    assert seen == ["http://fake.test/models", "http://fake.test/v1/models"]

    monkeypatch.setattr(model_catalog.requests, "get", lambda *_args, **_kwargs:
                        SimpleNamespace(status_code=200, ok=True, json=lambda: (_ for _ in ()).throw(ValueError())))
    with pytest.raises(ValueError, match="非 JSON"):
        fetch_models("http://fake.test/v1", "fake-key", 2)


@pytest.mark.parametrize("status, expected", [(401, "密钥无效"), (403, "密钥无效"),
                                              (404, "不支持模型列表")])
def test_model_http_errors(monkeypatch, status, expected):
    from src.utils import model_catalog

    monkeypatch.setattr(model_catalog.requests, "get", lambda *_args, **_kwargs:
                        SimpleNamespace(status_code=status, ok=False))
    with pytest.raises(ValueError, match=expected):
        fetch_models("http://fake.test/v1", "fake-key", 2)


def test_model_timeout_and_network_errors(monkeypatch):
    import requests
    from src.utils import model_catalog

    for error, expected in [(requests.Timeout(), "超时"),
                            (requests.ConnectionError(), "网络连接失败")]:
        def fail(*_args, **_kwargs):
            raise error

        monkeypatch.setattr(model_catalog.requests, "get", fail)
        with pytest.raises(ValueError, match=expected):
            fetch_models("http://fake.test/v1", "fake-key", 2)
