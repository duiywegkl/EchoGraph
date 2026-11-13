"""Atomic filesystem storage for bases, deltas, snapshots, and chats."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from uuid import uuid4

from .graph import Delta, GraphState


class StoreError(RuntimeError):
    """Stored timeline data is missing or inconsistent."""


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Registration:
    kind: str
    chat_uuid: str


class TimelineStore:
    def __init__(self, root, snapshot_every=10):
        if not isinstance(snapshot_every, int) or snapshot_every < 1:
            raise ValueError("snapshot_every must be positive")
        self.root = Path(root)
        self.snapshot_every = snapshot_every
        self._write_lock = RLock()
        for name in ("bases", "deltas", "snapshots", "chats", "manual"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def _path(self, folder, key):
        if not isinstance(key, str) or not key or "/" in key or "\\" in key or key in (".", ".."):
            raise StoreError("invalid storage key")
        return self.root / folder / f"{key}.json"

    def _read(self, folder, key):
        path = self._path(folder, key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"missing or invalid {folder} record: {key}") from exc

    def _write(self, folder, key, value):
        path = self._path(folder, key)
        fd, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def put_base(self, base_hash, state):
        with self._write_lock:
            path = self._path("bases", base_hash)
            if path.exists():
                if self.get_base(base_hash) != state:
                    raise StoreError(f"base hash collision: {base_hash}")
                return
            self._write("bases", base_hash, state.to_dict())

    def get_base(self, base_hash):
        return GraphState.from_dict(self._read("bases", base_hash))

    def get_chat(self, chat_uuid):
        return self._read("chats", chat_uuid)

    def put_chat(self, chat):
        chat = dict(chat)
        chat["updated_at"] = _now()
        self._write("chats", chat["chat_uuid"], chat)

    def register_chat(self, chat_uuid, integrity, owner, file_name, previous_file_exists=False, *, base_hash=None, derived_chat_uuid=None):
        """Register a file identity; a copied identity becomes a new chat."""
        path = self._path("chats", chat_uuid)
        if not path.exists():
            if base_hash is None:
                raise StoreError("base_hash is required for a new chat")
            self.get_base(base_hash)
            self.put_chat({"chat_uuid": chat_uuid, "integrity": integrity, "owner": owner,
                           "file_name": file_name, "base_hash": base_hash,
                           "parent_chat_uuid": None, "head_key": None,
                           "status": "consistent", "last_error": None})
            self._write("manual", chat_uuid, {"edits": [], "cursor": 0})
            return Registration("new", chat_uuid)
        parent = self.get_chat(chat_uuid)
        if integrity == parent["integrity"] and file_name == parent["file_name"]:
            return Registration("same", chat_uuid)
        if integrity == parent["integrity"] and not previous_file_exists:
            parent["file_name"] = file_name
            self.put_chat(parent)
            return Registration("renamed", chat_uuid)
        child_uuid = derived_chat_uuid or str(uuid4())
        self.put_chat({"chat_uuid": child_uuid, "integrity": integrity, "owner": owner,
                       "file_name": file_name, "base_hash": parent["base_hash"],
                       "parent_chat_uuid": chat_uuid, "head_key": parent["head_key"],
                       "status": parent["status"], "last_error": parent["last_error"]})
        source_layer = self._path("manual", chat_uuid)
        if source_layer.exists():
            self._write("manual", child_uuid, self._read("manual", chat_uuid))
        else:
            self._write("manual", child_uuid, {"edits": [], "cursor": 0})
        return Registration("derived", child_uuid)

    def has_delta(self, key):
        return self._path("deltas", key).exists()

    def get_delta(self, key):
        record = self._read("deltas", key)
        if record.get("key") != key:
            raise StoreError(f"delta key mismatch: {key}")
        Delta.from_dict(record["delta"])
        return record

    def put_delta(self, segment, base_hash, delta, extractor_info=None):
        with self._write_lock:
            if self.has_delta(segment.key):
                existing = self.get_delta(segment.key)
                if (existing["parent_key"] != segment.parent_key or
                        existing["segment_hash"] != segment.segment_hash or
                        existing["base_hash"] != base_hash):
                    raise StoreError(f"delta key collision: {segment.key}")
                return
            self._write("deltas", segment.key,
                        {"key": segment.key, "parent_key": segment.parent_key,
                         "base_hash": base_hash, "turn_index": segment.turn,
                         "segment_hash": segment.segment_hash, "delta": delta.to_dict(),
                         "created_at": _now(), "extractor_info": extractor_info or {}})

    def put_snapshot(self, key, state):
        with self._write_lock:
            path = self._path("snapshots", key)
            if not path.exists():
                self._write("snapshots", key, state.to_dict())

    def state_at(self, key, base_hash):
        if key is None:
            return self.get_base(base_hash)
        chain = []
        seen = set()
        cursor = key
        snapshot_key = None
        while cursor is not None:
            if cursor in seen:
                raise StoreError(f"delta parent cycle: {cursor}")
            seen.add(cursor)
            record = self.get_delta(cursor)
            if record["base_hash"] != base_hash:
                raise StoreError(f"base mismatch at delta: {cursor}")
            chain.append(record)
            if self._path("snapshots", cursor).exists():
                snapshot_key = cursor
                break
            cursor = record["parent_key"]
        state = (GraphState.from_dict(self._read("snapshots", snapshot_key))
                 if snapshot_key else self.get_base(base_hash))
        for record in reversed(chain):
            if record["key"] != snapshot_key:
                Delta.from_dict(record["delta"]).apply_forward(state)
        return state
