from __future__ import annotations

from mozilcode.daemon.session_records import SessionRecords
from mozilcode.daemon.session_store import SessionStore


def test_session_records_loads_persisted_sessions_sorted_by_created_at(tmp_path):
    store = SessionStore(tmp_path)
    store.persist_meta("old", {"work_dir": "/old", "title": "Old", "created_at": 1})
    store.persist_meta("new", {"work_dir": "/new", "title": "New", "created_at": 2})
    store.persist_events("new", [{"type": "LoopComplete"}], 0)

    records = SessionRecords(store, "/server")

    assert records.load_persisted() == 2
    assert records.list_infos() == [
        {"id": "new", "work_dir": "/new", "title": "New"},
        {"id": "old", "work_dir": "/old", "title": "Old"},
    ]
    assert records.event_log("new") == [{"type": "LoopComplete"}]


def test_session_records_create_emit_persist_and_close(tmp_path):
    store = SessionStore(tmp_path)
    records = SessionRecords(store, "/server")

    records.create("sid", "/workspace")
    records.emit("sid", {"type": "UserMessage"})
    records.emit("sid", None)
    records.persist_events("sid")

    assert records.has("sid")
    assert records.work_dir("sid") == "/workspace"
    assert store.load_sessions()[0].events == [{"type": "UserMessage"}]

    log_ref = records.event_log("sid")
    records.close("sid")

    assert records.event_log("sid") is None
    assert log_ref is not None and log_ref[-1] is None
    assert not store.session_dir("sid").exists()


def test_session_records_sets_blank_title_from_prompt_once(tmp_path):
    store = SessionStore(tmp_path)
    records = SessionRecords(store, "/server")
    prompt = "x" * 45

    records.create("sid", "/workspace")
    records.set_title_from_prompt("sid", prompt)
    records.set_title_from_prompt("sid", "replacement")

    assert records.info("sid")["title"] == "x" * 40
    assert store.load_sessions()[0].meta["title"] == "x" * 40
