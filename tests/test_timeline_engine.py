from threading import Event, Thread

import pytest

from src.timeline import GraphState, TimelineEngine, TimelineStore, segment_messages


def message(role, content, ident=None, included=True):
    ident = ident or f"{role}:{content}"
    return {"msg_id": ident, "version_id": ident, "role": role, "content": content,
            "included": included}


def timeline(opening="add node A", *turns):
    result = [message("assistant", opening)] if opening else []
    for user, reply in turns:
        result += [message("user", user), message("assistant", reply)]
    return result


class FakeExtractor:
    def __init__(self):
        self.calls = []
        self.contents = []
        self.fail_turn = None
        self.bad_turn = None
        self.started = None
        self.release = None

    def extract(self, state, segments):
        self.calls.append([segment.turn for segment in segments])
        self.contents.append([[msg["content"] for msg in segment.messages]
                              for segment in segments])
        if self.started:
            self.started.set()
            assert self.release.wait(5)
        if self.fail_turn in [segment.turn for segment in segments]:
            raise RuntimeError("fake extractor failed")
        ops = []
        for segment in segments:
            for msg in segment.messages:
                text = msg["content"]
                if text.startswith("add node "):
                    name = text.removeprefix("add node ")
                    ops.append({"turn": segment.turn, "op": "add_node", "id": name,
                                "name": name, "type": "character"})
                elif text.startswith("delete "):
                    ops.append({"turn": segment.turn, "op": "delete_node", "id": text[7:]})
                elif " relation " in text:
                    source, target = text.split(" relation ")
                    ops.append({"turn": segment.turn, "op": "add_edge",
                                "id": f"{source}:{target}:{segment.turn}", "source": source,
                                "target": target, "relation": "relation"})
        if self.bad_turn is not None:
            if self.bad_turn == "missing":
                del ops[0]["turn"]
            else:
                ops[0]["turn"] = self.bad_turn
        return ops


@pytest.fixture
def setup(tmp_path):
    store = TimelineStore(tmp_path, snapshot_every=2)
    store.put_base("base1", GraphState())
    store.register_chat("parent", "i1", "owner", "parent.jsonl", base_hash="base1")
    fake = FakeExtractor()
    return store, TimelineEngine(store, fake), fake


def names(result):
    return set(result.state.nodes)


def test_segmentation_hash_open_turn_and_exclusion():
    msgs = [message("assistant", "hello", "one"), message("narrator", "scene"),
            message("user", " u1 "), message("user", "u2"),
            message("assistant", "reply"), message("user", "unfinished"),
            message("assistant", "ignored", included=False)]
    segments = segment_messages(msgs, "base")
    assert len(segments) == 2
    assert [len(s.messages) for s in segments] == [2, 3]
    replacement = [dict(m, msg_id="other", version_id="swipe-other") for m in msgs]
    assert [s.key for s in segment_messages(replacement, "base")] == [s.key for s in segments]
    assert segment_messages([message("user", "waiting")], "base")[0].messages == ()


def test_line_break_edit_reuses_key_and_preserves_extractor_text(setup):
    _, engine, fake = setup
    original = [message("assistant", "first line\n\nsecond line", "opening")]
    edited = [dict(original[0], content="first line  \nsecond line")]

    assert segment_messages(original, "base1")[0].key == segment_messages(edited, "base1")[0].key
    assert segment_messages(original, "base1")[0].messages[0]["content"] == "first line\n\nsecond line"
    engine.process("parent", original)
    assert fake.contents == [[["first line\n\nsecond line"]]]
    engine.process("parent", edited)
    assert fake.calls == [[0]]


def test_swipes_edit_hide_cut_and_new_reply(setup):
    store, engine, fake = setup
    base = timeline("add node A", ("hi", "add node B"))
    assert names(engine.process("parent", base, "per_turn")) == {"A", "B"}
    assert fake.calls == [[0], [1]]
    b = [dict(base[0], content="add node C")] + base[1:]
    assert names(engine.process("parent", b, "per_turn")) == {"C", "B"}
    calls = len(fake.calls)
    assert names(engine.process("parent", base, "per_turn")) == {"A", "B"}
    assert len(fake.calls) == calls
    prefix = base[:1]
    assert names(engine.process("parent", prefix, "per_turn")) == {"A"}
    assert len(fake.calls) == calls
    new_swipe = base[:2] + [dict(base[2], content="add node D", version_id="new")]
    assert names(engine.process("parent", new_swipe, "per_turn")) == {"A", "D"}
    calls = len(fake.calls)
    assert names(engine.process("parent", base, "per_turn")) == {"A", "B"}
    assert len(fake.calls) == calls
    edited = [dict(base[0], content="add node A")] + [dict(base[1], content="edited", msg_id=base[1]["msg_id"])] + base[2:]
    assert names(engine.process("parent", edited, "per_turn")) == {"A", "B"}
    assert len(fake.calls) == calls + 1
    hidden = [dict(base[0], included=False)] + base[1:]
    assert names(engine.process("parent", hidden, "per_turn")) == {"B"}
    calls = len(fake.calls)
    assert names(engine.process("parent", base, "per_turn")) == {"A", "B"}
    assert len(fake.calls) == calls


def test_hidden_middle_message_delete_open_turn_and_empty_opening(setup):
    store, engine, fake = setup
    msgs = timeline("", ("u1", "add node A"), ("u2", "add node B"),
                    ("u3", "A relation B"))
    msgs.insert(3, message("narrator", "scene"))
    full = engine.process("parent", msgs, "per_turn")
    assert names(full) == {"A", "B"} and len(full.state.edges) == 1
    assert fake.calls == [[1], [2], [3]]
    hidden = msgs[:3] + [dict(msgs[3], included=False)] + msgs[4:]
    before = len(fake.calls)
    result = engine.process("parent", hidden, "per_turn")
    assert result.first_changed_turn == 2
    assert fake.calls[before:] == [[2], [3]]
    before = len(fake.calls)
    assert engine.process("parent", msgs, "per_turn").state == full.state
    assert len(fake.calls) == before
    cut = msgs[:5]
    assert names(engine.process("parent", cut, "per_turn")) == {"A", "B"}
    assert len(fake.calls) == before
    deletion = timeline("", ("u1", "add node A"), ("u2", "add node B"),
                        ("u3", "delete B"))
    assert names(engine.process("parent", deletion, "per_turn")) == {"A"}
    assert len(engine.sync("parent", deletion).state.edges) == 0
    unfinished = deletion + [message("user", "waiting")]
    before = len(fake.calls)
    assert engine.process("parent", unfinished, "per_turn").state == engine.sync("parent", deletion).state
    assert len(fake.calls) == before


def test_early_edit_recomputes_suffix_and_branch_is_independent(setup):
    store, engine, fake = setup
    parent = timeline("add node A", ("one", "add node B"), ("two", "add node C"))
    engine.process("parent", parent, "per_turn")
    child = store.register_chat("parent", "new-integrity", "owner", "child.jsonl")
    assert child.kind == "derived" and child.chat_uuid != "parent"
    extension = parent + [message("user", "three"), message("assistant", "add node D")]
    assert names(engine.process(child.chat_uuid, extension, "per_turn")) == {"A", "B", "C", "D"}
    assert fake.calls[-1] == [3]
    edited = parent[:1] + [dict(parent[1], content="edited")] + parent[2:]
    before = len(fake.calls)
    engine.process("parent", edited, "per_turn")
    assert fake.calls[before:] == [[1], [2]]
    assert names(engine.sync(child.chat_uuid, extension)) == {"A", "B", "C", "D"}


def test_registry_rename_copy_and_pinned_base(setup):
    store, engine, fake = setup
    parent = timeline("add node A")
    engine.process("parent", parent)
    renamed = store.register_chat("parent", "i1", "owner", "new.jsonl", False)
    assert renamed.kind == "renamed"
    assert store.register_chat("parent", "i1", "owner", "new.jsonl").kind == "same"
    copied = store.register_chat("parent", "i1", "owner", "copy.jsonl", True)
    assert copied.kind == "derived"
    assert store.get_chat(copied.chat_uuid)["parent_chat_uuid"] == "parent"
    store.put_base("base2", GraphState())
    store.register_chat("fresh", "i2", "owner", "fresh.jsonl", base_hash="base2")
    assert store.get_chat("parent")["base_hash"] == "base1"
    assert store.get_chat("fresh")["base_hash"] == "base2"


def test_batch_tags_and_per_turn_equivalence(tmp_path):
    store = TimelineStore(tmp_path)
    store.put_base("base", GraphState())
    store.register_chat("batch", "batch", "o", "batch", base_hash="base")
    fake = FakeExtractor()
    engine = TimelineEngine(store, fake)
    msgs = timeline("add node A", ("u1", "add node B"), ("u2", "A relation B"))
    batch = engine.process("batch", msgs)
    second_store = TimelineStore(tmp_path / "second")
    second_store.put_base("base", GraphState())
    second_store.register_chat("single", "single", "o", "single", base_hash="base")
    single_fake = FakeExtractor()
    single = TimelineEngine(second_store, single_fake).process("single", msgs, "per_turn")
    assert batch.state == single.state
    assert fake.calls == [[0, 1, 2]]
    assert single_fake.calls == [[0], [1], [2]]
    keys = segment_messages(msgs, "base")
    assert [len(store.get_delta(seg.key)["delta"]["ops"]) for seg in keys] == [1, 1, 1]


@pytest.mark.parametrize("bad", ["missing", 99, True])
def test_bad_batch_turn_keeps_head(setup, bad):
    store, engine, fake = setup
    original = timeline("add node A")
    engine.process("parent", original)
    old = store.get_chat("parent")["head_key"]
    fake.bad_turn = bad
    with pytest.raises(ValueError, match="turn"):
        engine.process("parent", timeline("add node A", ("u", "add node B")))
    assert store.get_chat("parent")["head_key"] == old
    assert store.get_chat("parent")["status"] == "inconsistent"


def test_per_turn_failure_retains_head_and_retry_skips_success(setup):
    store, engine, fake = setup
    original = timeline("add node A")
    engine.process("parent", original, "per_turn")
    old = store.get_chat("parent")["head_key"]
    extended = timeline("add node A", ("u1", "add node B"), ("u2", "add node C"))
    fake.fail_turn = 2
    with pytest.raises(RuntimeError, match="failed"):
        engine.process("parent", extended, "per_turn")
    assert store.get_chat("parent")["head_key"] == old
    assert store.get_chat("parent")["status"] == "inconsistent"
    assert names(engine.sync("parent", extended)) == {"A"}
    fake.fail_turn = None
    before = len(fake.calls)
    assert names(engine.process("parent", extended, "per_turn")) == {"A", "B", "C"}
    assert fake.calls[before:] == [[2]]


def test_snapshots_replay_and_missing_head_delta(setup):
    store, engine, fake = setup
    msgs = timeline("add node A", ("u1", "add node B"), ("u2", "add node C"))
    result = engine.process("parent", msgs, "per_turn")
    keys = segment_messages(msgs, "base1")
    assert (store.root / "snapshots" / f"{keys[1].key}.json").exists()
    assert store.state_at(result.head_key, "base1") == result.state
    (store.root / "deltas" / f"{result.head_key}.json").unlink()
    damaged = engine.sync("parent", msgs)
    assert not damaged.consistent
    assert "missing or invalid deltas" in store.get_chat("parent")["last_error"]


def test_snapshot_replay_skips_older_deltas(setup):
    store, engine, fake = setup
    msgs = timeline("add node A", ("u1", "add node B"), ("u2", "add node C"))
    result = engine.process("parent", msgs, "per_turn")
    opening_key = segment_messages(msgs, "base1")[0].key
    (store.root / "deltas" / f"{opening_key}.json").unlink()
    assert store.state_at(result.head_key, "base1") == result.state


def test_stale_process_cannot_replace_newer_sync(setup):
    store, engine, fake = setup
    old = timeline("add node A")
    engine.process("parent", old)
    requested = timeline("add node A", ("u", "add node B"))
    fake.started, fake.release = Event(), Event()
    outcomes = []
    thread = Thread(target=lambda: outcomes.append(engine.process("parent", requested)))
    thread.start()
    assert fake.started.wait(5)
    newer = engine.sync("parent", old)
    fake.release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert store.get_chat("parent")["head_key"] == newer.head_key
    assert outcomes[0].consistent is False
