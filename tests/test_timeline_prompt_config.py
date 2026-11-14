"""Prompt retrieval and reload behavior use isolated stores and fake clients."""

from src.timeline.graph import GraphState
from src.timeline.tavern import TavernTimeline
from src.utils.config import config
from src.timeline.initialization import extraction_prompt
from src.timeline.extractor import TimelineExtractor


class FakeClient:
    def __init__(self):
        self.model = config.llm.model


def test_extraction_prompts_require_source_language():
    base = extraction_prompt('阿青', '旅人', '', '', '', '', '', '')
    assert '名称、描述和关系标签必须与原文使用相同语言' in base
    assert '2–6 个汉字' in base
    extractor = TimelineExtractor(FakeClient())
    from src.timeline.graph import GraphState
    from types import SimpleNamespace
    segment = SimpleNamespace(turn=1, messages=[{'role': 'user', 'content': '阿青看见古城'}])
    timeline = extractor.request_text(GraphState(), [segment])
    assert '名称、描述和关系标签必须与对话原文使用相同语言' in timeline
    assert '2–6 个汉字' in timeline


def registered(service, state):
    service.register('chat', 'integrity', 'owner', 'file')
    service.store.put_base('base-test', state)
    chat = service.store.get_chat('chat')
    chat['base_hash'] = 'base-test'
    service.store.put_chat(chat)
    return chat


def test_prompt_selects_relevant_nodes_and_bounds_context(tmp_path, monkeypatch):
    service = TavernTimeline(tmp_path, FakeClient)
    nodes = {f'n{i}': {'name': f'Node {i}', 'type': 'character',
                       'description': 'unrelated background'} for i in range(200)}
    nodes['n199']['name'] = 'Lantern'
    nodes['n198']['name'] = 'Harbor'
    state = GraphState(nodes, {'near': {'source': 'n199', 'target': 'n198', 'relation': 'visits'}})
    chat = registered(service, state)
    chat['timeline_messages'] = [{'role': 'user', 'content': 'Where is Lantern now?',
                                  'included': True}]
    service.store.put_chat(chat)
    monkeypatch.setattr(config.memory, 'max_context_length', 900)
    content = service.prompt('chat')['content']
    assert '## 最近对话' in content and '## 相关知识图谱' in content
    assert 'Lantern (角色)' in content
    assert 'Lantern' in content and 'Harbor' in content and 'visits' in content
    assert 'Node 0' not in content
    assert len(content) <= 900


def test_processing_and_base_build_read_current_config_each_run(tmp_path, monkeypatch):
    service = TavernTimeline(tmp_path, FakeClient)
    chat = registered(service, GraphState())
    chat['timeline_messages'] = [{'role': 'assistant', 'content': 'Opening', 'included': True}]
    chat['books'] = [{'source': 'global', 'name': 'world', 'entries': [
        {'uid': 1, 'key': ['place'], 'content': 'A place', 'disable': False}]}]
    service.store.put_chat(chat)
    runs = []
    service.engine.process = lambda _uuid, messages, mode, *, extractor: runs.append(
        (mode, len(messages), extractor.model, extractor.context_size))
    monkeypatch.setattr(config.timeline, 'per_turn_regen', False)
    monkeypatch.setattr(config.timeline, 'include_global_persona_books', False)
    monkeypatch.setattr(config.llm, 'context_size', 1000)
    monkeypatch.setattr(config.llm, 'model', 'first')
    service._work('chat')
    monkeypatch.setattr(config.timeline, 'per_turn_regen', True)
    monkeypatch.setattr(config.timeline, 'include_global_persona_books', True)
    monkeypatch.setattr(config.llm, 'context_size', 2000)
    monkeypatch.setattr(config.llm, 'model', 'second')
    service._work('chat')
    assert runs == [('batch', 1, 'first', 1000), ('per_turn', 2, 'second', 2000)]

    built = []
    monkeypatch.setattr('src.timeline.tavern.build_base',
                        lambda _source, client, _store, _progress, **kwargs:
                        built.append((client.model, kwargs['context_size'])))
    service._build_base('owner', {'card': {}}, 'unused')
    assert built == [('second', 2000)]
