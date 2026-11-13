"""Persistent, replayable manual graph edits for one chat."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from .graph import GraphError


def effective_state(head_state, layer):
    """Replay applied edits without mutating the timeline head.

    Missing targets and invalid endpoints are reported rather than aborting
    the rest of the layer.  A clear is represented by individual deletions.
    """
    state = head_state.copy()
    skipped = []
    for edit in layer.get("edits", [])[:layer.get("cursor", 0)]:
        op = (deepcopy(edit['payload']['ops']) if edit['op'] == 'edit_set'
              else [{"op": edit["op"], **deepcopy(edit["payload"])}])
        failed = False
        for item in op:
            try:
                state.apply([item])
            except (GraphError, KeyError, TypeError, ValueError):
                failed = True
        if failed:
            skipped.append(edit)
    return state, skipped


class ManualLayer:
    def __init__(self, store, chat_uuid):
        self.store = store
        self.chat_uuid = chat_uuid
        path = store._path("manual", chat_uuid)
        self.data = store._read("manual", chat_uuid) if path.exists() else {"edits": [], "cursor": 0}

    @property
    def can_undo(self):
        return self.data["cursor"] > 0

    @property
    def can_redo(self):
        return self.data["cursor"] < len(self.data["edits"])

    def _save(self):
        self.store._write("manual", self.chat_uuid, self.data)

    def apply(self, op, payload, head_state):
        state, _ = effective_state(head_state, self.data)
        trial = state.copy()
        ops = payload['ops'] if op == 'edit_set' else [{"op": op, **deepcopy(payload)}]
        trial.apply(ops)
        if op == 'edit_set':
            before = state.to_dict()
        else:
            ident = payload["id"]
            table = state.nodes if op.endswith("node") else state.edges
            before = deepcopy(table.get(ident))
        edit = {"edit_id": str(uuid4()), "op": op, "payload": deepcopy(payload),
                "before": before, "created_at": datetime.now(timezone.utc).isoformat()}
        self.data["edits"] = self.data["edits"][:self.data["cursor"]] + [edit]
        self.data["cursor"] += 1
        self._save()
        return edit

    def undo(self):
        if self.can_undo:
            self.data["cursor"] -= 1
            self._save()
            return True
        return False

    def redo(self):
        if self.can_redo:
            self.data["cursor"] += 1
            self._save()
            return True
        return False
