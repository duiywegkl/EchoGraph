import copy
import json
import shutil
from pathlib import Path

import networkx as nx

from src.timeline.engine import TimelineEngine
from src.timeline.graph import GraphState
from src.timeline.local import (active_content, graphml_state, register_local,
                                state_to_memory, timeline_messages)
from src.timeline.manual import ManualLayer, effective_state
from src.timeline.store import TimelineStore


def test_manual_stacking_undo_reload_skip_and_derived(tmp_path):
    store = TimelineStore(tmp_path / 'timeline')
    head = GraphState({'a': {'name': 'A', 'type': 'character'},
                       'b': {'name': 'B', 'type': 'character'}},
                      {'base-edge': {'source': 'a', 'target': 'b', 'relation': 'knows'}})
    store.put_base('base', head)
    store.register_chat('parent', 'one', 'local', 'parent.json', base_hash='base')
    layer = ManualLayer(store, 'parent')
    layer.apply('update_node', {'id': 'a', 'description': 'first'}, head)
    layer.apply('update_node', {'id': 'a', 'description': 'second'}, head)
    layer.apply('add_edge', {'id': 'manual-edge', 'source': 'a', 'target': 'b', 'relation': 'trusts'}, head)
    state, skipped = effective_state(head, layer.data)
    assert state.nodes['a']['description'] == 'second'
    assert len(state.edges) == 2 and not skipped
    assert layer.undo() and layer.undo()
    assert layer.can_redo
    layer.apply('delete_edge', {'id': 'base-edge'}, head)
    assert not layer.can_redo
    reloaded = ManualLayer(store, 'parent')
    assert reloaded.data == layer.data
    smaller = GraphState({'b': {'name': 'B', 'type': 'character'}}, {})
    _, skipped = effective_state(smaller, reloaded.data)
    assert len(skipped) == 2
    registration = store.register_chat('parent', 'two', 'local', 'child.json',
                                       previous_file_exists=True)
    assert registration.kind == 'derived'
    assert ManualLayer(store, registration.chat_uuid).data == layer.data


def test_manual_clear_is_one_undoable_edit(tmp_path):
    store = TimelineStore(tmp_path / 'timeline')
    head = GraphState({'a': {'name': 'A', 'type': 'character'},
                       'b': {'name': 'B', 'type': 'character'}},
                      {'e': {'source': 'a', 'target': 'b', 'relation': 'knows'}})
    layer = ManualLayer(store, 'chat')
    layer.apply('edit_set', {'ops': [{'op': 'delete_edge', 'id': 'e'},
                                    {'op': 'delete_node', 'id': 'a'},
                                    {'op': 'delete_node', 'id': 'b'}]}, head)
    assert effective_state(head, layer.data)[0] == GraphState()
    assert len(layer.data['edits']) == 1
    assert layer.undo()
    assert effective_state(head, layer.data)[0] == head
    assert ManualLayer(store, 'chat').redo()
    assert effective_state(head, ManualLayer(store, 'chat').data)[0] == GraphState()


def test_legacy_graph_and_conversation_migration_without_llm(tmp_path):
    from run_ui import ConversationManager
    source = Path(__file__).resolve().parents[1] / 'data/local_conversations'
    original = next((source / 'conversations').glob('*.json'))
    ident = original.stem
    root = tmp_path / 'local_conversations'
    (root / 'conversations').mkdir(parents=True)
    shutil.copy2(original, root / 'conversations' / original.name)
    graph_source = source / 'graphs' / ident / 'knowledge_graph.graphml'
    (root / 'graphs' / ident).mkdir(parents=True)
    shutil.copy2(graph_source, root / 'graphs' / ident / graph_source.name)
    old_bytes = original.read_bytes(), graph_source.read_bytes()
    manager = ConversationManager(root)
    conv = manager.conversations[ident]
    assert conv['name'] == '0号对话'
    assert set(conv['messages'][0]) == {'msg_id', 'role', 'active', 'swipes'}
    chat = manager.timeline_store.get_chat(ident)
    state = manager.timeline_store.state_at(chat['head_key'], chat['base_hash'])
    old = graphml_state(graph_source)
    assert state == old
    assert set(state.nodes) == set(nx.read_graphml(graph_source).nodes)
    assert len(state.edges) == nx.read_graphml(graph_source).number_of_edges()
    manager._save_conversation(conv)
    saved = json.loads((root / 'conversations' / original.name).read_text(encoding='utf-8'))
    assert saved['metadata']['integrity']
    assert saved['messages'][0]['swipes'][0]['version_id']
    assert (original.read_bytes(), graph_source.read_bytes()) == old_bytes


def test_first_run_default_then_blank(tmp_path):
    from run_ui import ConversationManager
    manager = ConversationManager(tmp_path / 'local_conversations')
    default = manager.get_current_conversation()
    assert default['name'] == '0号对话' and len(default['messages']) == 1
    chat = manager.timeline_store.get_chat(default['id'])
    assert manager.timeline_store.state_at(chat['head_key'], chat['base_hash']).nodes
    ident = manager.create_conversation('新建对话')
    blank = manager.conversations[ident]
    assert blank['messages'] == []
    chat = manager.timeline_store.get_chat(ident)
    assert manager.timeline_store.get_base(chat['base_hash']) == GraphState()


def test_engine_swipe_edit_delete_branch_and_retry(tmp_path):
    store = TimelineStore(tmp_path / 'timeline')
    class Fake:
        calls = []
        fail = False
        def extract(self, state, segments):
            self.calls.append(tuple(s.turn for s in segments))
            if self.fail:
                raise RuntimeError('fake failure')
            return [{'turn': s.turn, 'op': 'add_node', 'id': f'n{s.turn}_{len(self.calls)}',
                     'name': f'N{s.turn}', 'type': 'character'} for s in segments]
    fake = Fake()
    engine = TimelineEngine(store, fake)
    conv = {'id': 'p', 'metadata': {'integrity': 'p'}, 'messages': []}
    register_local(store, conv)
    def msg(role, content):
        return {'msg_id': content, 'role': role, 'active': 0,
                'swipes': [{'version_id': content, 'content': content, 'timestamp': 0}]}
    conv['messages'] = [msg('user', 'u1'), msg('assistant', 'a1')]
    assert engine.process('p', timeline_messages(conv)).consistent


    assert len(fake.calls) == 1
    conv['messages'][1]['swipes'].append({'version_id': 'a2', 'content': 'a2', 'timestamp': 0})
    conv['messages'][1]['active'] = 1
    engine.process('p', timeline_messages(conv))
    assert len(fake.calls) == 2
    conv['messages'][1]['active'] = 0
    engine.process('p', timeline_messages(conv))
    assert len(fake.calls) == 2
    conv['messages'] += [msg('user', 'u2'), msg('assistant', 'a3')]
    engine.process('p', timeline_messages(conv), mode='per_turn')
    assert len(fake.calls) == 3
    child = copy.deepcopy(conv)
    child.update(id='c', metadata={'integrity': 'c'})
    register_local(store, child, parent_id='p')
    engine.process('c', timeline_messages(child))
    assert len(fake.calls) == 3
    child['messages'] += [msg('user', 'u3'), msg('assistant', 'a4')]
    engine.process('c', timeline_messages(child))
    assert len(fake.calls) == 4
    assert store.get_chat('p')['head_key'] != store.get_chat('c')['head_key']
    conv['messages'][0]['swipes'][0]['content'] = 'edited'
    engine.process('p', timeline_messages(conv))
    assert len(fake.calls) == 5
    conv['messages'] = conv['messages'][:2]
    engine.process('p', timeline_messages(conv))
    assert len(fake.calls) == 5
    conv['messages'][0]['swipes'][0]['content'] = 'failure'
    fake.fail = True
    try:
        engine.process('p', timeline_messages(conv))
    except RuntimeError:
        pass
    assert store.get_chat('p')['status'] == 'inconsistent'
    fake.fail = False
    assert engine.process('p', timeline_messages(conv)).consistent


def test_batch_and_per_turn_grouping(tmp_path):
    class Fake:
        def __init__(self):
            self.groups = []
        def extract(self, state, segments):
            self.groups.append(tuple(item.turn for item in segments))
            return []
    for mode, expected in [('batch', [(1, 2)]), ('per_turn', [(1,), (2,)])]:
        store = TimelineStore(tmp_path / mode)
        conv = {'id': mode, 'metadata': {'integrity': mode}, 'messages': []}
        register_local(store, conv)
        for role, content in [('user', 'one'), ('assistant', 'reply one'),
                              ('user', 'two'), ('assistant', 'reply two')]:
            conv['messages'].append({'msg_id': content, 'role': role, 'active': 0,
                                     'swipes': [{'version_id': content, 'content': content,
                                                 'timestamp': 0}]})
        fake = Fake()
        assert TimelineEngine(store, fake).process(mode, timeline_messages(conv), mode=mode).consistent
        assert fake.groups == expected


def test_multiedge_memory_and_tavern_graphml(tmp_path):
    from src.graph.knowledge_graph import KnowledgeGraph
    state = GraphState({'a': {'name': 'A', 'type': 'character'},
                        'b': {'name': 'B', 'type': 'character'}},
                       {'e1': {'source': 'a', 'target': 'b', 'relation': 'likes'},
                        'e2': {'source': 'a', 'target': 'b', 'relation': 'trusts'}})
    class Memory:
        knowledge_graph = KnowledgeGraph()
    memory = Memory()
    state_to_memory(state, memory)
    assert memory.knowledge_graph.graph.number_of_edges() == 2
    assert {d['edge_id'] for _, _, d in memory.knowledge_graph.graph.edges(data=True)} == {'e1', 'e2'}
    context = memory.knowledge_graph.to_text_representation()
    assert 'likes' in context and 'trusts' in context
    source = (Path(__file__).resolve().parents[1]
              / 'data/tavern_characters/elara/sessions/current/knowledge_graph.graphml')
    path = tmp_path / 'tavern.graphml'
    shutil.copy2(source, path)
    graph = KnowledgeGraph()
    graph.load_graph(str(path))
    original = nx.read_graphml(path)
    assert set(graph.graph.nodes) == set(original.nodes)
    assert graph.graph.number_of_edges() == original.number_of_edges()
