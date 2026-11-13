"""P2 extraction contracts; every model call uses an in-process fake."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.timeline.base import BaseGraphBuilder, base_hash, build_base, lore_messages
from src.timeline.budget import estimate_tokens, plan_groups
from src.timeline.engine import TimelineEngine
from src.timeline.extractor import (ExtractionRequestError, ExtractionValidationError,
                                    TimelineExtractor)
from src.timeline.graph import GraphState
from src.timeline.segments import segment_messages
from src.timeline.store import TimelineStore


class FakeLLM:
    model = 'fake-model'

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat_with_metadata(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=response, finish_reason=None)


def source():
    return {'card': {'name': '阿青', 'description': '旅人', 'personality': '勇敢',
                     'scenario': '山中', 'mes_example': '你好', 'first_mes': '开局'},
            'books': [{'name': '设定', 'source': 'character', 'entries': [
                {'uid': 2, 'key': ['山'], 'keysecondary': [], 'content': '山中有龙', 'disable': False},
                {'uid': 1, 'key': [], 'keysecondary': [], 'content': '禁用', 'disable': True}]},
                {'name': '聊天', 'source': 'chat', 'entries': [
                    {'uid': 3, 'key': ['线索'], 'content': '钥匙', 'disable': False}]}]}


def msg(role, content):
    return {'role': role, 'content': content, 'included': True,
            'msg_id': f'{role}:{content}', 'version_id': f'{role}:{content}'}


def turns(n, lore=None):
    messages = [msg('assistant', '开局')]
    for index in range(1, n):
        messages += [msg('user', f'问{index}'), msg('assistant', f'答{index}')]
    return (lore or []) + messages


def test_base_hash_scope_normalization_and_changes():
    original = source()
    target = base_hash(original)
    variant = deepcopy(original)
    variant['card'].update(avatar='x', first_mes='换开局', alternate_greetings=['换'], creator_notes='x')
    variant['books'][0]['entries'].reverse()
    variant['books'][0]['entries'][0]['content'] = '禁用\r\n  '
    variant['books'][0]['entries'][1]['content'] = '山中有龙  '
    variant['books'][1]['entries'][0]['content'] = '变化'
    assert base_hash(variant) != target  # disabled base entry still participates
    variant['books'][0]['entries'][0]['content'] = '禁用'
    assert base_hash(variant) == target
    for field in ('description', 'personality', 'scenario', 'mes_example'):
        changed = deepcopy(original)
        changed['card'][field] += '新'
        assert base_hash(changed) != target
    for field, value in [('content', '新'), ('key', ['新']), ('disable', True)]:
        changed = deepcopy(original)
        changed['books'][0]['entries'][0][field] = value
        assert base_hash(changed) != target


def test_base_reuse_and_multiedges(tmp_path):
    llm = FakeLLM(['{"main_character":{"name":"阿青","type":"character"},'
                   '"entities":[{"name":"山","type":"location"}],'
                   '"relationships":[{"source":"阿青","target":"山","relationship":"住在"},'
                   '{"source":"阿青","target":"山","relationship":"守护"}]}'] * 2)
    store = TimelineStore(tmp_path)
    digest, state = build_base(source(), llm, store)
    assert len(state.edges) == 2 and len(set(state.edges)) == 2
    assert '首条消息：\n' in llm.calls[0][0][1]['content']
    assert '开局' not in llm.calls[0][0][1]['content']
    again, cached = build_base(source(), llm, store)
    assert (again, cached) == (digest, state)
    assert BaseGraphBuilder(store).build_base(source(), llm) == (digest, state)
    assert len(llm.calls) == 2  # card and world-book batch, no cache call


def test_lore_is_opening_and_invalidates_every_key():
    value = source()
    messages = turns(3, lore_messages(value))
    keys = [s.key for s in segment_messages(messages, 'base')]
    assert segment_messages(messages, 'base')[0].messages[0]['role'] == 'lorebook'
    assert segment_messages(turns(3) + lore_messages(value), 'base')[0].key == keys[0]
    value['books'][1]['entries'][0]['content'] = '新钥匙'
    assert all(a != b for a, b in zip(keys, [s.key for s in segment_messages(
        turns(3, lore_messages(value)), 'base')]))
    value['books'].append({'name': '全局', 'source': 'global', 'entries': [
        {'uid': 4, 'content': '天空', 'disable': False}]})
    off = segment_messages(turns(3, lore_messages(value, False)), 'base')
    on = segment_messages(turns(3, lore_messages(value, True)), 'base')
    assert all(a.key != b.key for a, b in zip(off, on))


@pytest.mark.parametrize('text,expected', [('你好 world! 12', 11), ('中A-BC，3\n', 7),
                                           ('hi there', 5), ('𠀀カ한!', 7)])
def test_token_estimate(text, expected):
    assert estimate_tokens(text) == expected


def test_budget_plans_whole_turns_and_oversize():
    items = list(range(5))
    assert plan_groups(items, 8, lambda group: '中' * len(group)) == [[0, 1], [2, 3], [4]]
    assert plan_groups(items, 0, lambda group: '') == [items]
    assert plan_groups(items, 2, lambda group: 'a' * 10) == [[0], [1], [2], [3], [4]]


def _extract(reply, state=None):
    llm = FakeLLM([reply] * 4)
    return TimelineExtractor(llm), llm, state or GraphState()


@pytest.mark.parametrize('operation', [
    {'op': 'add_node', 'turn': 0, 'id': 1, 'name': 'A', 'type': 'character'},
    {'op': 'add_node', 'turn': 0, 'id': 'A', 'name': 1, 'type': 'character'},
    {'op': 'add_node', 'id': 'A', 'name': 'A', 'type': 'character'},
    {'op': 'add_node', 'turn': 99, 'id': 'A', 'name': 'A', 'type': 'character'},
    {'op': 'mystery', 'turn': 0, 'id': 'A'},
    {'op': 'update_node', 'turn': 0, 'id': 'missing', 'name': 'X'},
    {'op': 'add_node', 'turn': 0, 'id': 'A', 'name': 'A', 'type': 'nonsense'},
])
def test_validator_repairs_three_times_then_fails(operation):
    import json
    extractor, llm, state = _extract(json.dumps({'operations': [operation]}))
    with pytest.raises(ExtractionValidationError):
        extractor.extract(state, segment_messages([msg('assistant', '开局')], 'base'))
    assert len(llm.calls) == 4


def test_edge_ids_are_deterministic_and_multiedges():
    reply = ('{"operations":['
             '{"turn":0,"op":"add_node","id":"A","name":"甲","type":"角色"},'
             '{"turn":0,"op":"add_node","id":"B","name":"乙","type":"character"},'
             '{"turn":0,"op":"add_edge","source":"A","target":"B","relation":"朋友"},'
             '{"turn":0,"op":"add_edge","source":"A","target":"B","relation":"朋友"}]}')
    segments = segment_messages([msg('assistant', '开局')], 'base')
    first, _, _ = _extract(reply)
    second, _, _ = _extract(reply)
    ops = first.extract(GraphState(), segments)
    ids = [op['id'] for op in ops if op['op'] == 'add_edge']
    assert len(set(ids)) == 2
    assert ops == second.extract(GraphState(), segments)
    state = GraphState().apply([{k: v for k, v in op.items() if k != 'turn'} for op in ops])
    assert len(state.edges) == 2 and state.nodes['A']['type'] == 'character'


def test_update_can_reference_an_earlier_add_in_same_response():
    reply = ('{"operations":['
             '{"turn":0,"op":"add_node","id":"A","name":"甲","type":"character"},'
             '{"turn":0,"op":"update_node","id":"A","description":"更新"}]}')
    extractor, _, _ = _extract(reply)
    ops = extractor.extract(GraphState(), segment_messages([msg('assistant', '开局')], 'base'))
    assert [op['op'] for op in ops] == ['add_node', 'update_node']


@pytest.mark.parametrize('reply', ['', TimeoutError('timeout')])
def test_empty_and_transport_failures_are_request_errors(reply):
    llm = FakeLLM([reply])
    extractor = TimelineExtractor(llm)
    with pytest.raises(ExtractionRequestError):
        extractor.extract(GraphState(), segment_messages([msg('assistant', '开局')], 'base'))
    assert len(llm.calls) == 1
    assert 'max_tokens' not in llm.calls[0][1]


def _engine(tmp_path, extractor):
    store = TimelineStore(tmp_path)
    store.put_base('base', GraphState())
    store.register_chat('chat', 'i', 'owner', 'chat', base_hash='base')
    return TimelineEngine(store, extractor), store


class FailingExtractor:
    model = 'fake-model'
    context_size = 0

    def __init__(self, fail_turn=None, max_group=None, validation=False):
        self.calls = []
        self.fail_turn = fail_turn
        self.max_group = max_group
        self.validation = validation

    def extract(self, state, segments):
        group = [s.turn for s in segments]
        self.calls.append(group)
        if self.validation:
            raise ExtractionValidationError('invalid')
        if (self.max_group and len(group) > self.max_group) or self.fail_turn in group:
            raise ExtractionRequestError('request failed')
        return [{'turn': turn, 'op': 'add_node', 'id': f'n{turn}',
                 'name': f'n{turn}', 'type': 'character'} for turn in group]


def test_request_split_eight_turns_and_retry(tmp_path):
    fake = FailingExtractor(max_group=1, fail_turn=7)
    engine, store = _engine(tmp_path, fake)
    messages = turns(8)
    with pytest.raises(ExtractionRequestError):
        engine.process('chat', messages)
    assert [len(group) for group in fake.calls] == [8, 4, 2, 1, 1, 2, 1, 1, 4, 2, 1, 1, 2, 1, 1]
    assert store.get_chat('chat')['head_key'] is None
    assert store.get_chat('chat')['status'] == 'inconsistent'
    assert sum(store.has_delta(s.key) for s in segment_messages(messages, 'base')) == 7
    fake.fail_turn = None
    before = len(fake.calls)
    assert engine.process('chat', messages).consistent
    assert fake.calls[before:] == [[7]]
    record = store.get_delta(segment_messages(messages, 'base')[6].key)
    assert record['extractor_info'] == {'extractor': 'FailingExtractor', 'mode': 'batch',
                                        'group_size': 1, 'split_depth': 3, 'model': 'fake-model'}


def test_request_split_three_turns_single_failure_and_validation_no_split(tmp_path):
    fake = FailingExtractor(fail_turn=0)
    engine, store = _engine(tmp_path, fake)
    with pytest.raises(ExtractionRequestError):
        engine.process('chat', turns(3))
    assert fake.calls == [[0, 1, 2], [0]]
    fake.calls.clear()
    with pytest.raises(ExtractionRequestError):
        engine.process('chat', turns(1), 'per_turn')
    assert fake.calls == [[0]]
    fake.calls.clear()
    fake.validation = True
    with pytest.raises(ExtractionValidationError):
        engine.process('chat', turns(3))
    assert fake.calls == [[0, 1, 2]]


class BudgetExtractor(FailingExtractor):
    context_size = 8

    def request_text(self, state, segments):
        return '中' * len(segments)


def test_budget_group_success_is_stored_before_later_failure(tmp_path):
    fake = BudgetExtractor(fail_turn=3)
    engine, store = _engine(tmp_path, fake)
    messages = turns(5)
    with pytest.raises(ExtractionRequestError):
        engine.process('chat', messages)
    assert fake.calls == [[0, 1], [2, 3], [2], [3]]
    segments = segment_messages(messages, 'base')
    assert all(store.has_delta(seg.key) for seg in segments[:3])
    assert not any(store.has_delta(seg.key) for seg in segments[3:])
    assert store.get_chat('chat')['head_key'] is None
    fake.fail_turn = None
    before = len(fake.calls)
    result = engine.process('chat', messages)
    assert result.consistent and len(result.state.nodes) == 5
    assert fake.calls[before:] == [[3, 4]]


def test_validation_after_repair_does_not_split(tmp_path):
    llm = FakeLLM(['{"operations":[{"op":"bad","turn":0}]}'] * 4)
    engine, store = _engine(tmp_path, TimelineExtractor(llm))
    with pytest.raises(ExtractionValidationError):
        engine.process('chat', turns(3))
    assert len(llm.calls) == 4
    assert store.get_chat('chat')['status'] == 'inconsistent'
    assert store.get_chat('chat')['head_key'] is None
