"""Visible message segmentation and content-addressed chain keys."""

from dataclasses import dataclass
import hashlib
import json
import unicodedata


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _content(value):
    if not isinstance(value, str):
        raise ValueError("message content must be a string")
    return " ".join(unicodedata.normalize("NFC", value).split())


@dataclass(frozen=True)
class Segment:
    turn: int
    messages: tuple[dict, ...]
    segment_hash: str
    key: str = ""
    parent_key: str | None = None


def segment_messages(messages, base_hash):
    """Return complete segments, including the possibly empty opening."""
    visible = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("included"), bool):
            raise ValueError("message must have a boolean included field")
        if not message["included"]:
            continue
        if message.get("role") not in ("user", "assistant", "narrator"):
            raise ValueError("invalid visible message role")
        if not isinstance(message.get("msg_id"), str) or not isinstance(message.get("version_id"), str):
            raise ValueError("visible message ids must be strings")
        _content(message.get("content"))
        visible.append(dict(message))

    groups = [[]]
    has_reply = False
    for message in visible:
        if message["role"] == "user":
            if len(groups) == 1 or has_reply:
                groups.append([])
                has_reply = False
        elif len(groups) > 1:
            has_reply = True
        groups[-1].append(message)
    if len(groups) > 1 and not has_reply:
        groups.pop()

    result = []
    parent = None
    for turn, group in enumerate(groups):
        content = [[m["role"], _content(m["content"])] for m in group]
        digest = _hash(json.dumps(content, ensure_ascii=False, separators=(",", ":")))
        key = _hash(json.dumps(["base:" + base_hash if turn == 0 else parent, digest], separators=(",", ":")))
        result.append(Segment(turn, tuple(group), digest, key, parent))
        parent = key
    return result
