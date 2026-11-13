"""Deterministic, reversible graph state for timeline deltas."""

from copy import deepcopy
from dataclasses import dataclass
import json

from src.graph.node_types import TYPE_IDS, normalize_type


class GraphError(ValueError):
    """An operation or graph record is invalid."""


def _identifier(value, label):
    if not isinstance(value, str) or not value:
        raise GraphError(f"{label} must be a nonempty string")
    return value


def _record(kind, value):
    if not isinstance(value, dict):
        raise GraphError(f"{kind} must be an object")
    allowed = ({"name", "type", "subtype", "description", "attributes"} if kind == "node"
               else {"source", "target", "relation", "description", "attributes"})
    if set(value) - allowed:
        raise GraphError(f"unexpected {kind} fields: {sorted(set(value) - allowed)}")
    required = ("name", "type") if kind == "node" else ("source", "target", "relation")
    for field in required:
        _identifier(value.get(field), f"{kind}.{field}")
    if kind == "node":
        if not isinstance(value["type"], str):
            raise GraphError("node.type must be a string")
        category, subtype = normalize_type(value["type"], value.get("subtype"))
        if category not in TYPE_IDS:
            raise GraphError(f"invalid node type: {value['type']}")
        value["type"] = category
        if subtype:
            value["subtype"] = subtype
        else:
            value.pop("subtype", None)
    for field in ("subtype", "description") if kind == "node" else ("description",):
        if field in value and not isinstance(value[field], str):
            raise GraphError(f"{kind}.{field} must be a string")
    value.setdefault("attributes", {})
    if not isinstance(value["attributes"], dict):
        raise GraphError(f"{kind}.attributes must be an object")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise GraphError(f"{kind} must be JSON serialisable") from exc
    return value


class GraphState:
    def __init__(self, nodes=None, edges=None):
        self.nodes = deepcopy(nodes if nodes is not None else {})
        self.edges = deepcopy(edges if edges is not None else {})
        self._validate()

    def _validate(self):
        if not isinstance(self.nodes, dict) or not isinstance(self.edges, dict):
            raise GraphError("nodes and edges must be objects")
        for node_id, node in self.nodes.items():
            _identifier(node_id, "node id")
            _record("node", node)
        for edge_id, edge in self.edges.items():
            _identifier(edge_id, "edge id")
            _record("edge", edge)
            if edge["source"] not in self.nodes or edge["target"] not in self.nodes:
                raise GraphError(f"dangling endpoints on edge {edge_id}")

    def copy(self):
        return GraphState(self.nodes, self.edges)

    def to_dict(self):
        return {"nodes": {k: deepcopy(self.nodes[k]) for k in sorted(self.nodes)},
                "edges": {k: deepcopy(self.edges[k]) for k in sorted(self.edges)}}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"nodes", "edges"}:
            raise GraphError("graph must contain nodes and edges")
        return cls(value["nodes"], value["edges"])

    def __eq__(self, other):
        return isinstance(other, GraphState) and self.to_dict() == other.to_dict()

    def apply(self, ops):
        if not isinstance(ops, list):
            raise GraphError("ops must be a list")
        trial = self.copy()
        for op in ops:
            if not isinstance(op, dict):
                raise GraphError("operation must be an object")
            action = op.get("op")
            if action not in {"add_node", "update_node", "delete_node", "add_edge", "update_edge", "delete_edge"}:
                raise GraphError(f"unknown operation: {action}")
            ident = _identifier(op.get("id"), "operation id")
            kind = "node" if action.endswith("node") else "edge"
            table = trial.nodes if kind == "node" else trial.edges
            if action.startswith("add_"):
                if ident in table:
                    raise GraphError(f"{kind} already exists: {ident}")
                table[ident] = _record(kind, deepcopy({k: v for k, v in op.items() if k not in ("op", "id")}))
            elif action.startswith("update_"):
                if ident not in table:
                    raise GraphError(f"missing {kind}: {ident}")
                fields = {k: v for k, v in op.items() if k not in ("op", "id")}
                table[ident] = _record(kind, {**table[ident], **deepcopy(fields)})
            else:
                if set(op) != {"op", "id"}:
                    raise GraphError(f"delete_{kind} accepts only id")
                if ident not in table:
                    raise GraphError(f"missing {kind}: {ident}")
                del table[ident]
                if kind == "node":
                    trial.edges = {k: v for k, v in trial.edges.items()
                                   if v["source"] != ident and v["target"] != ident}
        trial._validate()
        self.nodes, self.edges = trial.nodes, trial.edges
        return self


@dataclass(frozen=True)
class Delta:
    ops: list[dict]

    def to_dict(self):
        return {"ops": deepcopy(self.ops)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or not isinstance(value.get("ops"), list):
            raise GraphError("delta must contain ops")
        return cls(deepcopy(value["ops"]))

    def _apply(self, state, reverse):
        trial = state.copy()
        for change in reversed(self.ops) if reverse else self.ops:
            action, ident = change["op"], change["id"]
            kind = "node" if action.endswith("node") else "edge"
            table = trial.nodes if kind == "node" else trial.edges
            expected = change["after"] if reverse else change["before"]
            replacement = change["before"] if reverse else change["after"]
            if table.get(ident) != expected:
                raise GraphError(f"delta preimage mismatch: {kind} {ident}")
            if replacement is None:
                table.pop(ident, None)
            else:
                table[ident] = deepcopy(replacement)
        trial._validate()
        state.nodes, state.edges = trial.nodes, trial.edges
        return state

    def apply_forward(self, state):
        return self._apply(state, False)

    def apply_reverse(self, state):
        return self._apply(state, True)


def diff(before, after):
    """Record whole-value changes in dependency-safe order."""
    changes = []
    for kind, old, new in (("edge", before.edges, after.edges), ("node", before.nodes, after.nodes)):
        for ident in sorted(old.keys() - new.keys()):
            changes.append({"op": f"delete_{kind}", "id": ident, "before": deepcopy(old[ident]), "after": None})
    for kind, old, new in (("node", before.nodes, after.nodes), ("edge", before.edges, after.edges)):
        for ident in sorted(new):
            if ident not in old or old[ident] != new[ident]:
                changes.append({"op": f"add_{kind}" if ident not in old else f"update_{kind}",
                                "id": ident, "before": deepcopy(old.get(ident)), "after": deepcopy(new[ident])})
    return Delta(changes)
