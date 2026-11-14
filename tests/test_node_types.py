import copy
import hashlib
import json
from collections import Counter
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


def test_legacy_entities_migrate_without_write(tmp_path):
    copied = tmp_path / 'entities.json'
    entities = ([{'name': f'角色{i}', 'type': '人物'} for i in range(7)]
                + [{'name': f'地点{i}', 'type': '地点'} for i in range(5)]
                + [{'name': f'物品{i}', 'type': '物资'} for i in range(10)]
                + [{'name': '法术', 'type': '异能'}])
    copied.write_text(json.dumps({'entities': entities, 'relationships': []},
                                 ensure_ascii=False), encoding='utf-8')
    before = hashlib.md5(copied.read_bytes()).hexdigest()
    memory = GRAGMemory(graph_save_path=str(tmp_path / 'missing.graphml'),
                        entities_json_path=str(copied))
    assert hashlib.md5(copied.read_bytes()).hexdigest() == before
    counts = Counter(attrs['type'] for _, attrs in memory.knowledge_graph.graph.nodes(data=True))
    assert counts == {'character': 7, 'location': 5, 'item': 10, 'other': 1}
    assert any(attrs['type'] == 'other' and attrs.get('subtype') == '异能'
               for _, attrs in memory.knowledge_graph.graph.nodes(data=True))
