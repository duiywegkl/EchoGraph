"""Persistent coordinates for one local graph or Tavern chat."""

import json
import math
import os
from pathlib import Path


def layout_path(entities_path=None, session_id=None, storage_root=None):
    if session_id is None:
        return Path(entities_path).parent / "layout.json"
    if not isinstance(session_id, str) or Path(session_id).name != session_id or session_id in ("", ".", ".."):
        raise ValueError("Invalid chat ID")
    return Path(storage_root) / "tavern_timeline" / "layouts" / f"{session_id}.json"


def _valid_positions(value, node_ids):
    if not isinstance(value, dict):
        return {}
    result = {}
    for node_id in node_ids:
        point = value.get(node_id)
        if (isinstance(point, dict) and all(isinstance(point.get(axis), (int, float))
                                             and not isinstance(point.get(axis), bool)
                                             and math.isfinite(point[axis]) for axis in ("x", "y"))):
            result[node_id] = {axis: float(point[axis]) for axis in ("x", "y")}
    return result


def load_layout(path, node_ids):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        clean = _valid_positions(raw, node_ids)
        if clean != raw:
            save_layout(path, clean, node_ids)
        return clean
    except (OSError, ValueError, TypeError):
        return {}


def save_layout(path, positions, node_ids):
    path = Path(path)
    clean = _valid_positions(positions, node_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return clean


def merge_layout(path, positions, node_ids):
    merged = load_layout(path, node_ids)
    merged.update(_valid_positions(positions, node_ids))
    return save_layout(path, merged, node_ids)


def clear_layout(path):
    Path(path).unlink(missing_ok=True)
