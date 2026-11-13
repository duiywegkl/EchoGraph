"""Local conversation schema and adapters for the timeline graph."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import networkx as nx

from .graph import Delta, GraphState
from .segments import segment_messages
from .store import StoreError


EMPTY_BASE_HASH = hashlib.sha256(b'echograph-local-empty-v1').hexdigest()


def example_state():
    from src.scenarios.chrono_trigger_scenario import get_chrono_trigger_scenario
    source = get_chrono_trigger_scenario()
    nodes = {}
    for group in source['entities'].values():
        for entity in group:
            ident = entity['name']
            nodes[ident] = {'name': ident, 'type': entity['type'],
                            'description': entity.get('description', ''),
                            'attributes': {k: v for k, v in entity.items()
                                           if k not in ('name', 'type', 'description')}}
    edges = {}
    for index, rel in enumerate(source['relationships']):
        edges[f'example_{index:06d}'] = {'source': rel['from'], 'target': rel['to'],
                                          'relation': rel['relationship'],
                                          'description': rel.get('description', '')}
    return source['character_card']['scenario'], GraphState(nodes, edges)


def normalize_conversation(conversation):
    """Upgrade legacy messages in memory; persistence happens on normal save."""
    conversation.setdefault('metadata', {})
    conversation['metadata'].setdefault('integrity', str(uuid4()))
    upgraded = []
    for message in conversation.get('messages', []):
        if 'swipes' in message:
            upgraded.append(message)
        else:
            upgraded.append({'msg_id': str(uuid4()), 'role': message['role'], 'active': 0,
                             'swipes': [{'version_id': str(uuid4()),
                                         'content': message.get('content', ''),
                                         'timestamp': message.get('timestamp', conversation.get('created_time', 0))}]})
    conversation['messages'] = upgraded
    return conversation


def active_content(message):
    return message['swipes'][message['active']]['content']


def timeline_messages(conversation):
    result = []
    for msg in conversation['messages']:
        swipe = msg['swipes'][msg['active']]
        result.append({'msg_id': msg['msg_id'], 'version_id': swipe['version_id'],
                       'role': msg['role'], 'content': swipe['content'], 'included': True})
    return result


def graphml_state(path):
    graph = nx.read_graphml(path)
    nodes = {}
    for ident, attrs in graph.nodes(data=True):
        attrs = dict(attrs)
        nodes[str(ident)] = {'name': str(attrs.pop('name', ident)),
                             'type': str(attrs.pop('type', 'other')),
                             'description': str(attrs.pop('description', '')),
                             'attributes': attrs}
        if 'subtype' in nodes[ident]['attributes']:
            nodes[ident]['subtype'] = str(nodes[ident]['attributes'].pop('subtype'))
    edges = {}
    for index, (source, target, attrs) in enumerate(graph.edges(data=True)):
        attrs = dict(attrs)
        ident = str(attrs.pop('edge_id', '') or f'legacy_{index:06d}')
        edges[ident] = {'source': source, 'target': target,
                        'relation': str(attrs.pop('relationship', attrs.pop('relation', 'related_to'))),
                        'description': str(attrs.pop('description', '')),
                        'attributes': attrs}
    return GraphState(nodes, edges)


def state_to_memory(state, memory):
    """Replace the in-memory graph consumed by retrieval and the graph page."""
    graph = nx.MultiDiGraph()
    for ident, node in state.nodes.items():
        graph.add_node(ident, name=node['name'], type=node['type'],
                       subtype=node.get('subtype', ''), description=node.get('description', ''),
                       **node.get('attributes', {}))
    for ident, edge in state.edges.items():
        graph.add_edge(edge['source'], edge['target'], key=ident, edge_id=ident,
                       relationship=edge['relation'], description=edge.get('description', ''),
                       **edge.get('attributes', {}))
    memory.knowledge_graph.graph = graph


def register_local(store, conversation, graph_path=None, *, parent_id=None, example=False):
    """Register a blank or migrated local chat without extraction."""
    ident = conversation['id']
    if parent_id:
        parent = store.get_chat(parent_id)
        # The store's derived registration path copies both the cached head and manual layer.
        store.register_chat(parent_id, conversation['metadata']['integrity'], 'local',
                            f'{ident}.json', previous_file_exists=True, derived_chat_uuid=ident)
        return
    try:
        store.get_chat(ident)
        return
    except StoreError:
        pass
    if example:
        _, state = example_state()
        digest = hashlib.sha256(json.dumps(state.to_dict(), ensure_ascii=False,
                                            sort_keys=True).encode('utf-8')).hexdigest()
    elif graph_path and Path(graph_path).exists():
        state = graphml_state(graph_path)
        digest = hashlib.sha256(Path(graph_path).read_bytes()).hexdigest()
    else:
        state, digest = GraphState(), EMPTY_BASE_HASH
    store.put_base(digest, state)
    store.register_chat(ident, conversation['metadata']['integrity'], 'local', f'{ident}.json', base_hash=digest)
    if (example or (graph_path and Path(graph_path).exists())) and conversation['messages']:
        # The existing example graph already includes its opening; preserve it
        # exactly and mark turn zero cached so migration never calls an LLM.
        opening = segment_messages(timeline_messages(conversation), digest)[0]
        store.put_delta(opening, digest, Delta([]))
        store.put_snapshot(opening.key, state)
        chat = store.get_chat(ident)
        chat['head_key'] = opening.key
        store.put_chat(chat)
