from __future__ import annotations

import pytest

from mozilcode.daemon.session_store import SessionStore, validate_session_id


def test_session_store_persists_and_loads_meta_and_events(tmp_path):
    store = SessionStore(tmp_path)
    sid = "session-a"
    meta = {"work_dir": "D:/work", "title": "hello"}
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
