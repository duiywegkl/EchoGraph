import json

from src.ui.graph_layout_store import clear_layout, layout_path, load_layout, merge_layout, save_layout


def test_local_layout_save_load_merge_and_stale_cleanup(tmp_path):
    path = layout_path(entities_path=tmp_path / "conversation-a" / "entities.json")
    assert path == tmp_path / "conversation-a" / "layout.json"
    save_layout(path, {"甲": {"x": 12, "y": 30}, "旧": {"x": 1, "y": 1}}, {"甲", "旧"})
    assert merge_layout(path, {"乙": {"x": -4, "y": 6}}, {"甲", "乙"}) == {
        "甲": {"x": 12.0, "y": 30.0}, "乙": {"x": -4.0, "y": 6.0}}
    assert json.loads(path.read_text(encoding="utf-8")) == load_layout(path, {"甲", "乙"})
    assert load_layout(path, {"乙"}) == {"乙": {"x": -4.0, "y": 6.0}}
    assert "甲" not in json.loads(path.read_text(encoding="utf-8"))


def test_tavern_layout_is_per_chat_and_clear(tmp_path):
    a = layout_path(session_id="session-a", storage_root=tmp_path)
    b = layout_path(session_id="session-b", storage_root=tmp_path)
    assert a == tmp_path / "tavern_timeline" / "layouts" / "session-a.json"
    assert a != b
    save_layout(a, {"甲": {"x": 1, "y": 2}}, {"甲"})
    assert load_layout(b, {"甲"}) == {}
    clear_layout(a)
    assert not a.exists()


def test_invalid_positions_are_not_restored(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text('{"ok":{"x":1,"y":2},"bad":{"x":NaN,"y":3}}', encoding="utf-8")
    assert load_layout(path, {"ok", "bad"}) == {"ok": {"x": 1.0, "y": 2.0}}
