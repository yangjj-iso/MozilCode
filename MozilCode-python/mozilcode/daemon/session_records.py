from __future__ import annotations

import logging

from mozilcode.daemon.session_meta import (
    new_session_meta,
    session_info_from_meta,
    session_work_dir_from_meta,
    sort_session_ids_by_created_at,
)
from mozilcode.daemon.session_store import SessionStore

log = logging.getLogger(__name__)


class SessionRecords:
    """In-memory session records with durable metadata/event persistence."""

    def __init__(self, store: SessionStore, server_work_dir: str) -> None:
        self.store = store
        self.server_work_dir = server_work_dir
        self.event_logs: dict[str, list[dict | None]] = {}
        self.session_meta: dict[str, dict] = {}
        self.persisted_count: dict[str, int] = {}

    def load_persisted(self) -> int:
        """Load persisted sessions from disk; runtimes are created lazily."""
        for session in self.store.load_sessions():
            self.event_logs[session.sid] = session.events
            self.session_meta[session.sid] = session.meta
            self.persisted_count[session.sid] = len(session.events)
        if self.session_meta:
            log.info("Loaded %d persisted session(s)", len(self.session_meta))
        return len(self.session_meta)

    def create(self, sid: str, work_dir: str) -> None:
        self.event_logs[sid] = []
        self.session_meta[sid] = new_session_meta(work_dir)
        self.persisted_count[sid] = 0
        self.persist_meta(sid)

    def has(self, sid: str) -> bool:
        return sid in self.event_logs

    def ensure_event_log(self, sid: str) -> None:
        self.event_logs.setdefault(sid, [])

    def event_log(self, sid: str) -> list[dict | None] | None:
        return self.event_logs.get(sid)

    def emit(self, sid: str, event: dict | None) -> None:
        log_list = self.event_logs.get(sid)
        if log_list is not None:
            log_list.append(event)

    def persist_meta(self, sid: str) -> None:
        self.store.persist_meta(sid, self.session_meta.get(sid, {}))

    def persist_events(self, sid: str) -> None:
        log_list = self.event_logs.get(sid)
        if log_list is None:
            return
        self.persisted_count[sid] = self.store.persist_events(
            sid,
            log_list,
            self.persisted_count.get(sid, 0),
        )

    def set_title_from_prompt(self, sid: str, prompt: str) -> None:
        meta = self.session_meta.get(sid)
        if meta is not None and not meta.get("title"):
            meta["title"] = prompt[:40]
            self.persist_meta(sid)

    def info(self, sid: str) -> dict:
        return session_info_from_meta(
            sid,
            self.session_meta.get(sid),
            self.server_work_dir,
        )

    def list_infos(self) -> list[dict]:
        sids = sort_session_ids_by_created_at(
            self.event_logs.keys(),
            self.session_meta,
        )
        return [self.info(sid) for sid in sids]

    def work_dir(self, sid: str) -> str | None:
        meta = self.session_meta.get(sid)
        if meta is None:
            return None
        return session_work_dir_from_meta(meta, self.server_work_dir)

    def update_work_dir(self, sid: str, work_dir: str) -> None:
        self.session_meta.setdefault(sid, {})["work_dir"] = work_dir
        self.persist_meta(sid)

    def meta(self, sid: str) -> dict:
        return self.session_meta.get(sid, {})

    def close(self, sid: str) -> None:
        log_list = self.event_logs.pop(sid, None)
        if log_list is not None:
            log_list.append(None)
        self.session_meta.pop(sid, None)
        self.persisted_count.pop(sid, None)
        self.store.delete_session(sid)
