from __future__ import annotations

import json
from pathlib import Path

import pytest

from mozilcode.daemon.session_store import SessionStore, validate_session_id


def test_session_store_persists_and_loads_meta_and_events(tmp_path):
    store = SessionStore(tmp_path)
    sid = "session-a"
    meta = {"work_dir": "D:/work", "title": "hello", "created_at": 123.5}
    events = [
        {"type": "UserMessage", "data": {"content": "hi"}},
        None,
        {"type": "LoopComplete", "data": {}},
    ]

    store.persist_meta(sid, meta)
    next_count = store.persist_events(sid, events, 0)
    loaded = store.load_sessions()

    assert next_count == 3
    assert len(loaded) == 1
    assert loaded[0].sid == sid
    assert loaded[0].meta == meta
    assert loaded[0].events == [
        {"type": "UserMessage", "data": {"content": "hi"}},
        {"type": "LoopComplete", "data": {}},
    ]


def test_session_store_appends_only_new_events(tmp_path):
    store = SessionStore(tmp_path)
    sid = "session-a"
    events = [{"type": "A"}, {"type": "B"}]

    store.persist_meta(sid, {"title": "append"})
    first_count = store.persist_events(sid, events, 0)
    second_count = store.persist_events(sid, [*events, {"type": "C"}], first_count)
    loaded = store.load_sessions()

    assert first_count == 2
    assert second_count == 3
    assert loaded[0].events == [{"type": "A"}, {"type": "B"}, {"type": "C"}]


def test_session_store_clamps_negative_persisted_count(tmp_path):
    store = SessionStore(tmp_path)
    sid = "session-a"
    events = [{"type": "A"}, {"type": "B"}]

    store.persist_meta(sid, {"title": "repair count"})
    next_count = store.persist_events(sid, events, -5)
    loaded = store.load_sessions()

    assert next_count == 2
    assert loaded[0].events == events


def test_session_store_clamps_oversized_persisted_count(tmp_path):
    store = SessionStore(tmp_path)
    sid = "session-a"
    events = [{"type": "A"}, {"type": "B"}]

    store.persist_meta(sid, {"title": "oversized count"})
    next_count = store.persist_events(sid, events, 99)
    loaded = store.load_sessions()

    assert next_count == 2
    assert loaded[0].events == []


def test_session_store_delete_removes_session_directory(tmp_path):
    store = SessionStore(tmp_path)
    sid = "session-a"
    store.persist_meta(sid, {"title": "remove me"})

    store.delete_session(sid)

    assert not store.session_dir(sid).exists()


def test_session_store_skips_corrupt_session_and_loads_valid_ones(tmp_path):
    store = SessionStore(tmp_path)
    store.persist_meta("valid", {"title": "ok"})
    store.persist_events("valid", [{"type": "LoopComplete"}], 0)

    corrupt = store.session_dir("corrupt")
    corrupt.mkdir(parents=True)
    (corrupt / "meta.json").write_text("{bad", encoding="utf-8")

    loaded = store.load_sessions()

    assert [session.sid for session in loaded] == ["valid"]
    assert loaded[0].events == [{"type": "LoopComplete"}]


def test_session_store_skips_malformed_event_lines(tmp_path):
    store = SessionStore(tmp_path)
    sid = "session-a"
    store.persist_meta(sid, {"title": "recover"})
    events_path = store.session_dir(sid) / "events.jsonl"
    events_path.write_text(
        '{"type": "UserMessage"}\n'
        '{bad\n'
        'null\n'
        '[]\n'
        '{"type": "LoopComplete"}\n',
        encoding="utf-8",
    )

    loaded = store.load_sessions()

    assert len(loaded) == 1
    assert loaded[0].events == [
        {"type": "UserMessage"},
        {"type": "LoopComplete"},
    ]


def test_session_store_skips_non_object_meta(tmp_path):
    store = SessionStore(tmp_path)
    sid = "session-a"
    session_dir = store.session_dir(sid)
    session_dir.mkdir(parents=True)
    (session_dir / "meta.json").write_text("[]", encoding="utf-8")

    assert store.load_sessions() == []


@pytest.mark.parametrize(
    "meta",
    [
        {"title": []},
        {"work_dir": []},
        {"created_at": True},
        {"created_at": "123"},
        {"created_at": -1},
    ],
)
def test_session_store_skips_meta_with_invalid_known_fields(tmp_path, meta):
    store = SessionStore(tmp_path)
    store.persist_meta("valid", {"title": "ok"})
    session_dir = store.session_dir("bad")
    session_dir.mkdir(parents=True)
    (session_dir / "meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )

    loaded = store.load_sessions()

    assert [session.sid for session in loaded] == ["valid"]


def test_session_store_preserves_unknown_meta_fields(tmp_path):
    store = SessionStore(tmp_path)
    meta = {"title": "ok", "custom": {"x": 1}}

    store.persist_meta("session-a", meta)
    loaded = store.load_sessions()

    assert loaded[0].meta == meta


def test_session_store_preserves_existing_meta_when_atomic_replace_fails(
    tmp_path,
    monkeypatch,
):
    store = SessionStore(tmp_path)
    sid = "session-a"
    original_meta = {"title": "old"}
    store.persist_meta(sid, original_meta)

    original_replace = Path.replace

    def fail_meta_replace(self, target):
        if Path(target).name == "meta.json":
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_meta_replace)

    store.persist_meta(sid, {"title": "new"})

    session_dir = store.session_dir(sid)
    assert json.loads((session_dir / "meta.json").read_text(encoding="utf-8")) == (
        original_meta
    )
    assert list(session_dir.glob(".meta.json.*.tmp")) == []


@pytest.mark.parametrize(
    "sid",
    ["../escape", "..", ".", "nested/session", "bad.id", "bad id", "", "a" * 65],
)
def test_session_store_rejects_unsafe_session_ids(tmp_path, sid):
    store = SessionStore(tmp_path)

    with pytest.raises(ValueError, match="session_id must be"):
        store.session_dir(sid)


def test_validate_session_id_keeps_supported_custom_ids():
    assert validate_session_id("session-a") == "session-a"
    assert validate_session_id("sid_runtime_1") == "sid_runtime_1"


def test_session_store_skips_invalid_session_directory_names(tmp_path):
    store = SessionStore(tmp_path)
    store.persist_meta("valid", {"title": "ok"})
    store.persist_events("valid", [{"type": "LoopComplete"}], 0)

    invalid = tmp_path / "bad.id"
    invalid.mkdir()
    (invalid / "meta.json").write_text('{"title": "bad"}', encoding="utf-8")

    loaded = store.load_sessions()

    assert [session.sid for session in loaded] == ["valid"]
