"""Group base inputs and single-card hash compatibility, with a fake model."""

from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

from src.timeline.base import base_hash, build_base
from src.timeline.store import TimelineStore


class FakeLLM:
    model = 'fake-model'

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat_with_metadata(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return SimpleNamespace(content=next(self.responses), finish_reason=None)


def _group():
    return {
        'cards': [
            {'name': 'Alice', 'description': 'A scout'},
            {'name': 'Bob', 'description': 'A healer'},
        ],
        'books': [
            {'source': source, 'name': name, 'entries': [
                {'uid': 1, 'content': content, 'key': [], 'keysecondary': [], 'disable': False},
            ]} for source, name, content in [
                ('character', 'Alice main', 'A mountain'),
                ('character_extra', 'Bob extra', 'A river'),
                ('embedded', 'character_book', 'A village'),
            ]
        ] + [{'source': 'chat', 'name': 'Chat', 'entries': [{'content': 'Chat lore'}]}],
    }


def test_group_hash_covers_every_card_and_character_book_regardless_of_order():
    source = _group()
    original = base_hash(source)
    reversed_source = deepcopy(source)
    reversed_source['cards'].reverse()
    reversed_source['books'].reverse()
    assert base_hash(reversed_source) == original
    for index in range(2):
        changed = deepcopy(source)
        changed['cards'][index]['description'] += ' changed'
        assert base_hash(changed) != original
    for index in range(3):
        changed = deepcopy(source)
        changed['books'][index]['entries'][0]['content'] += ' changed'
        assert base_hash(changed) != original
    changed = deepcopy(source)
    changed['books'][3]['entries'][0]['content'] += ' changed'
    assert base_hash(changed) == original


def test_single_card_hash_keeps_legacy_json_shape():
    source = {'card': {'name': 'Alice', 'description': 'A scout'}, 'books': []}
    legacy = {'card': {'name': 'Alice', 'description': 'A scout', 'personality': '',
                       'scenario': '', 'mes_example': ''}, 'books': []}
    expected = sha256(json.dumps(legacy, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')).encode('utf-8')).hexdigest()
    assert base_hash(source) == expected
    assert base_hash({'cards': [source['card']], 'books': []}) != expected


def test_group_build_extracts_both_cards_and_character_books(tmp_path):
    source = _group()
    llm = FakeLLM(['{"entities":[],"relationships":[]}'] * 4)
    digest, state = build_base(source, llm, TimelineStore(tmp_path))
    assert digest == base_hash(source)
    assert {node['name'] for node in state.nodes.values()} == {'Alice', 'Bob'}
    prompts = [call[0][1]['content'] for call in llm.calls]
    assert any('A scout' in prompt for prompt in prompts)
    assert any('A healer' in prompt for prompt in prompts)
    assert all(any(content in prompt for prompt in prompts)
               for content in ('A mountain', 'A river', 'A village'))
    assert all('Chat lore' not in prompt for prompt in prompts)
