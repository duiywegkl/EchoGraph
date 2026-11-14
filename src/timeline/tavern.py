"""Tavern-facing timeline service. No live session or legacy graph storage is used."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .base import base_hash, build_base, lore_messages
from .engine import TimelineEngine
from .extractor import TimelineExtractor
from .graph import GraphState
from .manual import ManualLayer, effective_state
from .retrieval import prompt_context
from .store import StoreError, TimelineStore
from src.utils.config import config


class TavernTimeline:
    def __init__(self, root, client_factory, *, executor=None):
        self.store = TimelineStore(root)
        self.client_factory = client_factory
        self.executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix='tavern-timeline')
        self.engine = TimelineEngine(self.store, None)
        self.lock = RLock()
        self.jobs = {}
        self.base_jobs = {}
        self.current_chat_uuid = None

    def _owner_key(self, owner):
        return sha256(owner.encode('utf-8')).hexdigest()

    def _owner_record(self, owner):
        path = self.store._path('owners', self._owner_key(owner))
        return self.store._read('owners', self._owner_key(owner)) if path.exists() else {}

    def register(self, chat_uuid, integrity, owner, file_name, previous_file_exists=False):
        if not all(isinstance(x, str) and x for x in (chat_uuid, integrity, owner, file_name)):
            raise ValueError('chat_uuid, integrity, owner and file_name are required')
        with self.lock:
            owner_record = self._owner_record(owner)
            building = owner_record.get('building_hash')
            digest = owner_record.get('base_hash')
            if building and building != digest:
                digest = 'pending-' + self._owner_key(owner) + '-' + building
                self.store.put_base(digest, GraphState())
            if not digest:
                digest = 'pending-' + self._owner_key(owner)
                self.store.put_base(digest, GraphState())
            previous = None
            try:
                previous = self.store.get_chat(chat_uuid)['file_name']
            except StoreError:
                pass
            result = self.store.register_chat(chat_uuid, integrity, owner, file_name,
                                              previous_file_exists, base_hash=digest)
            self.current_chat_uuid = result.chat_uuid
            return {'kind': result.kind, 'chat_uuid': result.chat_uuid,
                    'previous_file_name': previous, 'needs_base': digest.startswith('pending-')}

    def base(self, owner, source):
        if not isinstance(owner, str) or not owner or not isinstance(source, dict):
            raise ValueError('owner and source are required')
        digest = base_hash(source)
        with self.lock:
            current = self._owner_record(owner)
            if current.get('base_hash') == digest:
                return {'status': 'completed', 'base_hash': digest, 'progress': 100}
            job = self.base_jobs.get((owner, digest))
            if job and not job.done():
                return {'status': 'building', 'base_hash': digest,
                        'progress': self._owner_record(owner).get('progress', 0)}
            try:
                self.store.get_base(digest)
            except StoreError:
                pass
            else:
                self._bind_base(owner, digest)
                return {'status': 'completed', 'base_hash': digest, 'progress': 100}
            self.store._write('owners', self._owner_key(owner),
                              {**current, 'owner': owner, 'building_hash': digest,
                               'base_error': None, 'progress': 0})
            future = self.executor.submit(self._build_base, owner, source, digest)
            self.base_jobs[(owner, digest)] = future
            return {'status': 'building', 'base_hash': digest, 'progress': 0}

    def _bind_base(self, owner, digest):
        self.store._write('owners', self._owner_key(owner), {'owner': owner, 'base_hash': digest})
        pending = {'pending-' + self._owner_key(owner),
                   'pending-' + self._owner_key(owner) + '-' + digest}
        for path in (self.store.root / 'chats').glob('*.json'):
            chat = json.loads(path.read_text(encoding='utf-8'))
            if chat['owner'] == owner and chat['base_hash'] in pending and chat['head_key'] is None:
                chat['base_hash'] = digest
                self.store.put_chat(chat)
                if chat.get('timeline_messages') is not None:
                    self._schedule(chat['chat_uuid'])

    def _build_base(self, owner, source, digest):
        try:
            client = self.client_factory()
            context_size = config.llm.context_size
            def progress(value):
                with self.lock:
                    current = self._owner_record(owner)
                    self.store._write('owners', self._owner_key(owner),
                                      {**current, 'progress': value})
            build_base(source, client, self.store, progress, context_size=context_size)
            with self.lock:
                if self._owner_record(owner).get('building_hash') == digest:
                    self._bind_base(owner, digest)
        except Exception as exc:
            with self.lock:
                self.store._write('owners', self._owner_key(owner),
                                  {**self._owner_record(owner), 'owner': owner,
                                   'base_error': str(exc)})

    def sync(self, chat_uuid, messages, books=None):
        if not isinstance(messages, list) or not isinstance(books or [], list):
            raise ValueError('messages and books must be arrays')
        with self.lock:
            chat = self.store.get_chat(chat_uuid)
            chat['timeline_messages'] = messages
            chat['books'] = books or []
            chat['revision'] = chat.get('revision', 0) + 1
            self.store.put_chat(chat)
            self.engine.invalidate(chat_uuid)
            if not chat['base_hash'].startswith('pending-'):
                self._schedule(chat_uuid)
            return self.status(chat_uuid)

    def _schedule(self, chat_uuid):
        old = self.jobs.get(chat_uuid)
        if old and not old.done():
            return
        self.jobs[chat_uuid] = self.executor.submit(self._work, chat_uuid)

    def _work(self, chat_uuid):
        while True:
            per_turn = config.timeline.per_turn_regen
            include_global_persona = config.timeline.include_global_persona_books
            extractor = (TimelineExtractor(self.client_factory(), config.llm.context_size)
                         if self.engine.extractor is None or isinstance(self.engine.extractor, TimelineExtractor)
                         else self.engine.extractor)
            with self.lock:
                chat = self.store.get_chat(chat_uuid)
                revision = chat.get('revision', 0)
                messages = list(chat.get('timeline_messages') or [])
                books = list(chat.get('books') or [])
            messages = lore_messages({'books': books}, include_global_persona) + messages
            try:
                self.engine.process(chat_uuid, messages, 'per_turn' if per_turn else 'batch',
                                    extractor=extractor)
            except Exception:
                pass  # Engine persists the error and keeps the old head.
            with self.lock:
                if self.store.get_chat(chat_uuid).get('revision', 0) == revision:
                    return

    def retry(self, chat_uuid):
        with self.lock:
            chat = self.store.get_chat(chat_uuid)
            if 'timeline_messages' not in chat:
                raise ValueError('no timeline to retry')
            self.engine.invalidate(chat_uuid)
            self._schedule(chat_uuid)
            return self.status(chat_uuid)

    def status(self, chat_uuid):
        chat = self.store.get_chat(chat_uuid)
        owner = self._owner_record(chat['owner'])
        pending_base = chat['base_hash'].startswith('pending-')
        job = self.jobs.get(chat_uuid)
        processing = bool(job and not job.done())
        state = ('needs_base' if pending_base else 'processing' if processing
                 else chat['status'])
        return {'chat_uuid': chat_uuid, 'state': state, 'reason': owner.get('base_error') if pending_base
                else chat.get('last_error'), 'progress': owner.get('progress', 0) if pending_base else 100,
                'head_key': chat.get('head_key')}

    def graph(self, chat_uuid):
        chat = self.store.get_chat(chat_uuid)
        head = self.store.state_at(chat['head_key'], chat['base_hash'])
        layer = ManualLayer(self.store, chat_uuid)
        effective, skipped = effective_state(head, layer.data)
        nodes = [{'id': key, **node} for key, node in effective.nodes.items()]
        links = [{'edge_id': key, **edge, 'relationship': edge['relation']}
                 for key, edge in effective.edges.items()]
        return {'session_id': chat_uuid, 'chat_uuid': chat_uuid,
                'graph_data': {'nodes': nodes, 'links': links},
                'graph_stats': {'nodes': len(nodes), 'edges': len(links)},
                'manual': {'can_undo': layer.can_undo, 'can_redo': layer.can_redo,
                           'skipped': len(skipped)}, 'status': self.status(chat_uuid)}

    def edit(self, chat_uuid, op, payload):
        with self.lock:
            chat = self.store.get_chat(chat_uuid)
            head = self.store.state_at(chat['head_key'], chat['base_hash'])
            ManualLayer(self.store, chat_uuid).apply(op, payload, head)
            return self.graph(chat_uuid)

    def history(self, chat_uuid, action):
        with self.lock:
            layer = ManualLayer(self.store, chat_uuid)
            getattr(layer, action)()
            return self.graph(chat_uuid)

    def prompt(self, chat_uuid):
        chat = self.store.get_chat(chat_uuid)
        head = self.store.state_at(chat['head_key'], chat['base_hash'])
        effective, _ = effective_state(head, ManualLayer(self.store, chat_uuid).data)
        return {'chat_uuid': chat_uuid, 'content': prompt_context(
            effective, chat.get('timeline_messages') or [], config.memory.max_context_length)}
