from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_SESSIONS_DIR = Path.home() / ".mozilcode" / "daemon_sessions"
META_FILE = "meta.json"
EVENTS_FILE = "events.jsonl"


@dataclass
class PersistedSession:
    sid: str
    meta: dict
    events: list[dict | None]


class SessionStore:
    """On-disk session store used to replay conversations after daemon restarts."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_SESSIONS_DIR

    def session_dir(self, sid: str) -> Path:
        return self.root / sid

    def _ensure_root(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            log.warning("Cannot create sessions dir: %s", e)
            return False

    def load_sessions(self) -> list[PersistedSession]:
        if not self._ensure_root():
            return []

        sessions: list[PersistedSession] = []
        for directory in sorted(self.root.iterdir(), key=lambda p: p.name):
            if not directory.is_dir():
                continue
            sid = directory.name
            try:
                sessions.append(self._load_session(sid, directory))
            except Exception as e:
                log.warning("Failed to load session %s: %s", sid, e)
        return sessions

    def _load_session(self, sid: str, directory: Path) -> PersistedSession:
        meta = self._read_meta(directory)
        events = self._read_events(directory)
        return PersistedSession(sid=sid, meta=meta, events=events)

    def _read_meta(self, directory: Path) -> dict:
        return json.loads((directory / META_FILE).read_text(encoding="utf-8"))

    def _read_events(self, directory: Path) -> list[dict | None]:
        events: list[dict | None] = []
        events_path = directory / EVENTS_FILE
        if not events_path.exists():
            return events
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events

    def persist_meta(self, sid: str, meta: dict) -> None:
        try:
            directory = self.session_dir(sid)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / META_FILE).write_text(
                json.dumps(meta, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("Persist meta failed for %s: %s", sid, e)

    def persist_events(
        self,
        sid: str,
        log_list: list[dict | None],
        persisted_count: int,
    ) -> int:
        """Append new serialized events and return the updated persisted count."""
        new_events = [event for event in log_list[persisted_count:] if event is not None]
        if not new_events:
            return len(log_list)

        try:
            directory = self.session_dir(sid)
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / EVENTS_FILE).open("a", encoding="utf-8") as f:
                for event in new_events:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            return len(log_list)
        except Exception as e:
            log.warning("Persist events failed for %s: %s", sid, e)
            return persisted_count

    def delete_session(self, sid: str) -> None:
        shutil.rmtree(self.session_dir(sid), ignore_errors=True)
