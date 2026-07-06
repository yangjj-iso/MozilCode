from __future__ import annotations

from mozilcode.daemon.session_store import SessionStore


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
