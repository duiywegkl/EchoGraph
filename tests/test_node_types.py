import copy
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.graph.node_types import NODE_TYPES, TYPE_IDS, TYPE_LABELS, display_name, normalize_type
from src.ui import graph_temp_files
from src.memory.grag_memory import GRAGMemory
from src.utils.llm_json import validate_kg, validate_operations
from src.ui.generators.graph_html_generator import GraphHTMLGenerator
from src.ui import theme


def test_enum_shared_with_palette_and_page(tmp_path):
    assert tuple(theme.node_type_colors()) == TYPE_IDS
    assert TYPE_IDS == tuple(item.id for item in NODE_TYPES)
    path = tmp_path / 'graph.html'
    GraphHTMLGenerator().generate_graph_html('[]', '[]', path)
    html = path.read_text(encoding='utf-8')
    for item in NODE_TYPES:
        assert item.label in html and item.id in html
    assert '{{TYPE_METADATA}}' not in html


def test_prompt_contains_all_types(tmp_path):
    from src.core.game_engine import GameEngine
    from src.core.grag_update_agent import GRAGUpdateAgent
    from src.core.llm_client import ChatResult
    from src.graph.node_types import prompt_types

    definitions = prompt_types()
    assert '怪物、精英怪物、生物及怪物群体' in definitions
    assert '属性面板' in definitions
    assert '组织、势力、阵营、世界观设定、设定、规则、体系或抽象概念' in definitions
    assert '异能、技能、能力及 skill、ability、power' in definitions
    assert '具体词放 subtype' in definitions

    prompt = GameEngine._build_character_analysis_prompt(None, 'A', '', '', '', '', '', '')
    assert prompt_types() in prompt
    update_prompt = GRAGUpdateAgent._build_analysis_prompt(
        None, '', '', {'nodes': {}, 'edges': []})
    assert prompt_types() in update_prompt

    class Stub:
        calls = []
        def chat_with_metadata(self, messages, **kwargs):
            self.calls.append(messages[-1]['content'])
            return ChatResult(json.dumps({'entities': [], 'relationships': []}), 'stop')

    stub = Stub()
    memory = GRAGMemory(graph_save_path=str(tmp_path / 'graph.graphml'),
                        entities_json_path=str(tmp_path / 'entities.json'), auto_load_entities=False)
    engine = GameEngine(memory, None, None, None, SimpleNamespace(llm_client=stub))
    engine._perform_llm_analysis('Hero', '', '', '', '', '', '')
    assert prompt_types() in stub.calls[0]


def test_validator_repairs_synonyms_and_rejects_unknown():
    data = {'entities': [{'name': 'A', 'type': '\u5730\u70b9'},
                         {'name': 'B', 'type': '\u7269\u8d44'},
                         {'name': 'C', 'type': '\u4eba\u7269'}], 'relationships': []}
    result = validate_kg(copy.deepcopy(data))
    assert [e['type'] for e in result['entities']] == ['location', 'item', 'character']
    with pytest.raises(ValueError, match='type'):
        validate_kg({'entities': [{'name': 'X', 'type': 'galaxy'}], 'relationships': []})
    op = validate_operations({'operations': [{'type': 'add_node', 'node_type': '\u5730\u70b9'}]})
    assert op['operations'][0]['node_type'] == 'location'
    with pytest.raises(ValueError, match='node_type'):
        validate_operations({'operations': [{'type': 'add_node', 'node_type': 'galaxy'}]})


def test_unknown_migrates_and_display_name():
    assert normalize_type('galaxy') == ('other', 'galaxy')
    assert display_name('\u5730\u70b9_\u6559\u5b66\u697c') == '\u6559\u5b66\u697c'
    assert display_name('character_Hero', 'Actual') == 'Actual'


@pytest.mark.parametrize('word', ['异能', '技能', '能力', 'skill', 'ability', 'power'])
def test_ability_synonyms_keep_subtype(word):
    assert normalize_type(word) == ('other', word)


@pytest.mark.parametrize('word', ['怪物', '精英怪物', '怪物群体'])
def test_monsters_stay_characters(word):
    assert normalize_type(word) == ('character', word)


@pytest.mark.parametrize('word', ['组织', '势力', '阵营', '世界观', '世界观设定',
                                  '设定', '规则', '体系', 'faction', 'organization'])
def test_concept_synonyms_keep_subtype(word):
    assert normalize_type(word) == ('concept', word)


def test_graph_temp_file_cleanup_matches_only_exited_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_temp_files.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(graph_temp_files, '_pid_running', lambda pid: pid == 123)
    stale = [graph_temp_files.graph_page_path(456), graph_temp_files.tavern_placeholder_path(456)]
    active = graph_temp_files.graph_page_path(123)
    unrelated = [tmp_path / 'graph.html', tmp_path / 'echograph-graph-456.html.bak',
                 tmp_path / 'echograph-graph-oops.html']
    for path in [*stale, active, *unrelated]:
        path.write_text('test', encoding='utf-8')
    graph_temp_files.cleanup_stale_graph_pages()
    assert all(not path.exists() for path in stale)
    assert all(path.exists() for path in [active, *unrelated])


def test_graph_temp_file_cleanup_current_process(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_temp_files.tempfile, 'gettempdir', lambda: str(tmp_path))
    paths = [graph_temp_files.graph_page_path(), graph_temp_files.tavern_placeholder_path()]
    for path in paths:
        path.write_text('test', encoding='utf-8')
    graph_temp_files.cleanup_current_graph_pages()
    assert all(not path.exists() for path in paths)


def test_resource_cleanup_removes_current_graph_pages(tmp_path, monkeypatch):
    from src.ui.managers.resource_cleanup_manager import ResourceCleanupManager

    monkeypatch.setattr(graph_temp_files.tempfile, 'gettempdir', lambda: str(tmp_path))
    paths = [graph_temp_files.graph_page_path(), graph_temp_files.tavern_placeholder_path()]
    for path in paths:
        path.write_text('test', encoding='utf-8')
    manager = ResourceCleanupManager(SimpleNamespace())
    monkeypatch.setattr(manager, 'cleanup_llm_threads', lambda: None)
    monkeypatch.setattr(manager, 'cleanup_api_server', lambda: None)
    monkeypatch.setattr(manager, 'save_application_data', lambda: None)
    assert manager.cleanup_all_resources()
    assert all(not path.exists() for path in paths)


def test_real_copy_migrates_without_write(tmp_path):
    source = max(Path('data/tavern_characters').glob('*/sessions/current/entities.json'),
                 key=lambda p: len(json.loads(p.read_text(encoding='utf-8')).get('entities', [])))
    copied = tmp_path / 'entities.json'
    shutil.copyfile(source, copied)
    before = hashlib.md5(copied.read_bytes()).hexdigest()
    memory = GRAGMemory(graph_save_path=str(tmp_path / 'missing.graphml'),
                        entities_json_path=str(copied))
    assert hashlib.md5(copied.read_bytes()).hexdigest() == before
    counts = Counter(attrs['type'] for _, attrs in memory.knowledge_graph.graph.nodes(data=True))
    assert counts == {'character': 7, 'location': 5, 'item': 10, 'other': 1}
    assert any(attrs['type'] == 'other' and attrs.get('subtype') == '异能'
               for _, attrs in memory.knowledge_graph.graph.nodes(data=True))
    print('real copied entities distribution:', dict(counts))


def test_api_create_type_validation(tmp_path, monkeypatch):
    import api_server
    memory = GRAGMemory(graph_save_path=str(tmp_path / 'graph.graphml'),
                        entities_json_path=str(tmp_path / 'entities.json'), auto_load_entities=False)
    monkeypatch.setattr(api_server, 'sessions', {'types': SimpleNamespace(memory=memory)})
    async def send(*args):
        pass
    monkeypatch.setattr(api_server.manager, 'send_message', send)
    client = TestClient(api_server.app)
    url = '/sessions/types/nodes'
    assert client.post(url, json={'name': 'X', 'type': 'galaxy'}).status_code == 400
    assert client.post(url, json={'name': 'Car', 'type': '\u8f7d\u5177'}).status_code == 200
    assert memory.knowledge_graph.graph.nodes['Car']['type'] == 'item'
    assert memory.knowledge_graph.graph.nodes['Car']['subtype'] == '\u8f7d\u5177'
    assert {n['type'] for n in client.get('/sessions/types/export').json()['graph_data']['nodes']} == {'item'}
