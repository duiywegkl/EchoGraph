"""Cache-aware timeline synchronisation and extraction orchestration."""

from dataclasses import dataclass
from threading import Lock, RLock

from .graph import Delta, diff
from .segments import Segment, segment_messages
from .store import StoreError


@dataclass
class SyncResult:
    target_key: str
    head_key: str | None
    consistent: bool
    pending: list[Segment]
    first_changed_turn: int | None
    state: object


class TimelineEngine:
    def __init__(self, store, extractor):
        self.store = store
        self.extractor = extractor
        self._guard = Lock()
        self._locks = {}
        self._process_locks = {}
        self._generation = {}

    def _chat_locks(self, chat_uuid):
        with self._guard:
            return (self._locks.setdefault(chat_uuid, RLock()),
                    self._process_locks.setdefault(chat_uuid, Lock()))

    def _keys_at(self, head):
        keys = []
        seen = set()
        while head is not None:
            if head in seen:
                raise StoreError(f"delta parent cycle: {head}")
            seen.add(head)
            record = self.store.get_delta(head)
            keys.append(head)
            head = record["parent_key"]
        return list(reversed(keys))

    def _sync_locked(self, chat_uuid, messages):
        self._generation[chat_uuid] = self._generation.get(chat_uuid, 0) + 1
        chat = self.store.get_chat(chat_uuid)
        segments = segment_messages(messages, chat["base_hash"])
        target = segments[-1].key
        error = None
        try:
            old_keys = self._keys_at(chat["head_key"])
            old_state = self.store.state_at(chat["head_key"], chat["base_hash"])
        except StoreError as exc:
            old_keys = []
            old_state = self.store.get_base(chat["base_hash"])
            error = str(exc)

        new_keys = [segment.key for segment in segments]
        changed = next((index for index in range(min(len(old_keys), len(new_keys)))
                        if old_keys[index] != new_keys[index]), min(len(old_keys), len(new_keys)))
        if old_keys == new_keys:
            first_changed = None
        else:
            first_changed = changed

        # The empty opening is an anchor, not an extraction request.
        if not segments[0].messages and not self.store.has_delta(segments[0].key):
            self.store.put_delta(segments[0], chat["base_hash"], Delta([]))
            if self.store.snapshot_every == 1:
                self.store.put_snapshot(segments[0].key, self.store.get_base(chat["base_hash"]))
        pending = [segment for segment in segments if not self.store.has_delta(segment.key)]
        if not pending:
            try:
                target_state = self.store.state_at(target, chat["base_hash"])
            except (StoreError, ValueError) as exc:
                error = str(exc)
            else:
                chat.update(head_key=target, status="consistent", last_error=None)
                self.store.put_chat(chat)
                return SyncResult(target, target, True, [], first_changed, target_state)
        chat.update(status="inconsistent", last_error=error)
        self.store.put_chat(chat)
        return SyncResult(target, chat["head_key"], False, pending, first_changed, old_state)

    def sync(self, chat_uuid, messages):
        lock, _ = self._chat_locks(chat_uuid)
        with lock:
            return self._sync_locked(chat_uuid, messages)

    @staticmethod
    def _validated_ops(raw, turns):
        if not isinstance(raw, list):
            raise ValueError("extractor must return a list of operations")
        grouped = {turn: [] for turn in turns}
        for op in raw:
            if not isinstance(op, dict) or type(op.get("turn")) is not int or op["turn"] not in grouped:
                raise ValueError("extractor operation has a missing or invalid turn")
            grouped[op["turn"]].append({k: v for k, v in op.items() if k != "turn"})
        return grouped

    def _store_segment(self, segment, base_hash, state, ops):
        before = state.copy()
        state.apply(ops)
        self.store.put_delta(segment, base_hash, diff(before, state),
                             {"extractor": type(self.extractor).__name__})
        if (segment.turn + 1) % self.store.snapshot_every == 0:
            self.store.put_snapshot(segment.key, state)

    def process(self, chat_uuid, messages, mode="batch"):
        if mode not in ("batch", "per_turn"):
            raise ValueError("mode must be batch or per_turn")
        lock, process_lock = self._chat_locks(chat_uuid)
        with process_lock:
            with lock:
                result = self._sync_locked(chat_uuid, messages)
                generation = self._generation[chat_uuid]
                base_hash = self.store.get_chat(chat_uuid)["base_hash"]
            if not result.pending:
                return result
            segments = segment_messages(messages, base_hash)
            pending_turns = {segment.turn for segment in result.pending}
            first_missing = min(pending_turns)
            state = self.store.state_at(segments[first_missing].parent_key, base_hash)
            try:
                if mode == "batch":
                    raw = self.extractor.extract(state.copy(), result.pending)
                    grouped = self._validated_ops(raw, pending_turns)
                for segment in segments[first_missing:]:
                    if segment.turn not in pending_turns:
                        record = self.store.get_delta(segment.key)
                        Delta.from_dict(record["delta"]).apply_forward(state)
                        continue
                    if mode == "per_turn":
                        raw = self.extractor.extract(state.copy(), [segment])
                        grouped = self._validated_ops(raw, {segment.turn})
                    self._store_segment(segment, base_hash, state, grouped[segment.turn])
            except Exception as exc:
                with lock:
                    if self._generation[chat_uuid] == generation:
                        chat = self.store.get_chat(chat_uuid)
                        chat.update(status="inconsistent", last_error=str(exc))
                        self.store.put_chat(chat)
                raise
            with lock:
                if self._generation[chat_uuid] != generation:
                    chat = self.store.get_chat(chat_uuid)
                    return SyncResult(result.target_key, chat["head_key"], False, [],
                                      result.first_changed_turn,
                                      self.store.state_at(chat["head_key"], base_hash))
                chat = self.store.get_chat(chat_uuid)
                chat.update(head_key=result.target_key, status="consistent", last_error=None)
                self.store.put_chat(chat)
                return SyncResult(result.target_key, result.target_key, True, [],
                                  result.first_changed_turn, state)
