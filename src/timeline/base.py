"""Content-addressed base graph and chat-bound lore messages."""

import hashlib
import json
from collections import defaultdict

from src.graph.node_types import TYPE_IDS, SYNONYMS, normalize_type
from src.utils.llm_json import request_json, validate_kg

from .graph import GraphState
from .initialization import extraction_prompt, world_batches
from .store import StoreError

CARD_FIELDS = ('name', 'description', 'personality', 'scenario', 'mes_example')
BASE_SOURCES = {'character', 'character_extra', 'embedded'}
ENTRY_FIELDS = ('uid', 'key', 'keysecondary', 'content', 'disable')


def _clean(value):
    if isinstance(value, str):
        return '\n'.join(line.rstrip() for line in value.replace('\r\n', '\n').replace('\r', '\n').split('\n'))
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _entries(book):
    entries = []
    for entry in book.get('entries') or []:
        item = {field: _clean(entry.get(field, [] if field in ('key', 'keysecondary') else
                                   False if field == 'disable' else '')) for field in ENTRY_FIELDS}
        item['key'] = item['key'] or []
        item['keysecondary'] = item['keysecondary'] or []
        item['disable'] = bool(item['disable'])
        entries.append(item)
    return sorted(entries, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))


def _books(source, allowed):
    books = [{'name': _clean(book.get('name') or ''), 'entries': _entries(book)}
             for book in source.get('books') or [] if book.get('source') in allowed]
    return sorted(books, key=lambda book: json.dumps(book, ensure_ascii=False, sort_keys=True))


def _cards(source):
    if 'cards' not in source:
        return [{key: _clean((source.get('card') or {}).get(key) or '') for key in CARD_FIELDS}]
    cards = [{key: _clean((card or {}).get(key) or '') for key in CARD_FIELDS}
             for card in source['cards']]
    if not cards:
        raise ValueError('group base requires at least one card')
    return sorted(cards, key=lambda card: json.dumps(card, ensure_ascii=False, sort_keys=True))


def base_hash(source):
    payload = {'cards': _cards(source)} if 'cards' in source else {'card': _cards(source)[0]}
    payload['books'] = _books(source, BASE_SOURCES)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _entity_id(name, category):
    return f"{category}_{name.strip().lower().replace(' ', '_')}"


def _edge_id(source, target, relation, occurrence, prefix='base'):
    raw = json.dumps([prefix, source, target, relation, occurrence], ensure_ascii=False,
                     separators=(',', ':'))
    return 'edge_' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def lore_messages(source, include_global_persona=False):
    allowed = {'chat'} | ({'global', 'persona'} if include_global_persona else set())
    result = []
    for book in _books(source, allowed):
        for entry in book['entries']:
            if entry['disable']:
                continue
            content = f"{book['name']}\n" + json.dumps(
                {field: entry[field] for field in ('uid', 'key', 'keysecondary', 'content')},
                ensure_ascii=False, sort_keys=True)
            ident = hashlib.sha256(json.dumps([book['name'], entry], ensure_ascii=False,
                                              sort_keys=True).encode('utf-8')).hexdigest()
            result.append({'role': 'lorebook', 'content': content, 'msg_id': ident,
                           'version_id': ident, 'included': True})
    return result


def build_base(source, llm_client, store, progress=None, context_size=0):
    """Return (hash, state), reusing a stored base without calling the LLM."""
    digest = base_hash(source)
    try:
        return digest, store.get_base(digest)
    except StoreError:
        pass
    cards = _cards(source)
    world = json.dumps([{'book': book['name'], **entry} for book in _books(source, BASE_SOURCES)
                        for entry in book['entries'] if not entry['disable']], ensure_ascii=False)
    entities, relationships, seen_relations = {}, [], set()
    card_names = [card['name'] or 'Unknown Character' for card in cards]
    main_names = {name.strip().casefold() for name in card_names}
    canonical = {name.strip().casefold(): name for name in card_names}
    mains = []
    world_budget = min(6000, max(500, context_size * 2)) if context_size else 6000
    batches = world_batches(world, budget=world_budget)
    total = len(cards) + len(batches)
    completed = 0
    for card_index, (card, name) in enumerate(zip(cards, card_names)):
        main = {'name': name, 'type': 'character', 'attributes': {'is_main_character': True}}
        for batch in ([''] + batches if card_index == 0 else ['']):
            prompt = extraction_prompt(name, card['description'], card['personality'],
                                       card['scenario'], '', card['mes_example'], batch,
                                       ', '.join(list(canonical.values())[:80]))
            parsed, _ = request_json(llm_client, prompt,
                                 '你是知识图谱提取助手。只输出简洁的 JSON。', validate_kg)
            if parsed.get('main_character'):
                main.update(parsed['main_character'])
                main['name'] = name
            for entity in parsed['entities']:
                key = entity['name'].strip().casefold()
                if key not in main_names:
                    entities[key] = entity
                    canonical[key] = entity['name']
            for relation in parsed['relationships']:
                key = json.dumps(relation, ensure_ascii=False, sort_keys=True)
                if key not in seen_relations:
                    relationships.append(relation)
                    seen_relations.add(key)
            completed += 1
            if progress:
                progress(int(90 * completed / total))
        mains.append(main)
    nodes, names = {}, {}
    for entity in [*mains, *entities.values()]:
        raw_type = entity.get('type', 'character')
        if raw_type not in TYPE_IDS and raw_type.casefold() not in SYNONYMS:
            raise ValueError(f'unknown base node type: {raw_type}')
        category, subtype = normalize_type(raw_type, entity.get('subtype'))
        ident = _entity_id(entity['name'], category)
        node = {'name': entity['name'], 'type': category,
                'attributes': entity.get('attributes') or {}}
        if subtype:
            node['subtype'] = subtype
        if entity.get('description'):
            node['description'] = entity['description']
        nodes[ident] = node
        names[entity['name'].strip().casefold()] = ident
    edges, counts = {}, defaultdict(int)
    for relation in relationships:
        source_id = names.get(relation['source'].strip().casefold())
        target_id = names.get(relation['target'].strip().casefold())
        if not source_id or not target_id:
            continue
        triple = (source_id, target_id, relation['relationship'])
        counts[triple] += 1
        ident = _edge_id(*triple, counts[triple])
        edge = {'source': source_id, 'target': target_id, 'relation': relation['relationship'],
                'attributes': relation.get('attributes') or {}}
        if relation.get('description'):
            edge['description'] = relation['description']
        edges[ident] = edge
    state = GraphState(nodes, edges)
    store.put_base(digest, state)
    return digest, state


class BaseGraphBuilder:
    """Bind a timeline store for the two-argument build_base API."""

    def __init__(self, store):
        self.store = store

    def build_base(self, source, llm_client):
        return build_base(source, llm_client, self.store)
