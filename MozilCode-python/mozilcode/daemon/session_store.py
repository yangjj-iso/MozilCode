from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_SESSIONS_DIR = Path.home() / ".mozilcode" / "daemon_sessions"
META_FILE = "meta.json"
EVENTS_FILE = "events.jsonl"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class PersistedSession:
    sid: str
    meta: dict
    events: list[dict]


def validate_session_id(sid: str) -> str:
    if not isinstance(sid, str) or not SESSION_ID_PATTERN.fullmatch(sid):
        raise ValueError(
            "session_id must be 1-64 characters of letters, digits, '_' or '-'"
        )
    return sid


def _clean_meta(meta: object) -> dict:
    if not isinstance(meta, dict):
        raise ValueError(f"{META_FILE} must contain a JSON object")
    cleaned = dict(meta)
    for field_name in ("title", "work_dir"):
        if field_name in cleaned and not isinstance(cleaned[field_name], str):
            raise ValueError(f"{META_FILE}.{field_name} must be a string")
    if "created_at" in cleaned:
        created_at = cleaned["created_at"]
        if (
            not isinstance(created_at, (int, float))
            or isinstance(created_at, bool)
            or created_at < 0
        ):
            raise ValueError(f"{META_FILE}.created_at must be a non-negative number")
    return cleaned


def _event_slice_start(persisted_count: int, event_count: int) -> int:
    if persisted_count < 0:
        return 0
    if persisted_count > event_count:
        return event_count
    return persisted_count


def _write_json_atomically(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _serialize_events_jsonl(events: list[dict]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _append_text_durably(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


class SessionStore:
    """On-disk session store used to replay conversations after daemon restarts."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_SESSIONS_DIR

    def session_dir(self, sid: str) -> Path:
        return self.root / validate_session_id(sid)

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
                validate_session_id(sid)
                if not (directory / META_FILE).is_file():
                    log.debug(
                        "Skipping incomplete session %s: missing %s",
                        sid,
                        META_FILE,
                    )
                    continue
                sessions.append(self._load_session(sid, directory))
            except Exception as e:
                log.warning("Failed to load session %s: %s", sid, e)
        return sessions

    def _load_session(self, sid: str, directory: Path) -> PersistedSession:
        meta = self._read_meta(directory)
        events = self._read_events(directory)
        return PersistedSession(sid=sid, meta=meta, events=events)

    def _read_meta(self, directory: Path) -> dict:
        meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
        return _clean_meta(meta)

    def _read_events(self, directory: Path) -> list[dict]:
        events: list[dict] = []
        events_path = directory / EVENTS_FILE
        if not events_path.exists():
            return events
        for line_number, line in enumerate(
            events_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                log.warning(
                    "Skipping malformed event in %s line %d: %s",
                    events_path,
                    line_number,
                    e,
                )
                continue
            if not isinstance(event, dict):
                log.warning(
                    "Skipping non-object event in %s line %d",
                    events_path,
                    line_number,
                )
                continue
            events.append(event)
        return events

    def persist_meta(self, sid: str, meta: dict) -> None:
        try:
            directory = self.session_dir(sid)
            _write_json_atomically(directory / META_FILE, meta)
        except Exception as e:
            log.warning("Persist meta failed for %s: %s", sid, e)

    def persist_events(
        self,
        sid: str,
        log_list: list[dict | None],
        persisted_count: int,
    ) -> int:
        """Append new serialized events and return the updated persisted count."""
        start = _event_slice_start(persisted_count, len(log_list))
        new_events = [event for event in log_list[start:] if event is not None]
        if not new_events:
            return len(log_list)

        try:
            events_text = _serialize_events_jsonl(new_events)
            _append_text_durably(self.session_dir(sid) / EVENTS_FILE, events_text)
            return len(log_list)
        except Exception as e:
            log.warning("Persist events failed for %s: %s", sid, e)
            return persisted_count

    def delete_session(self, sid: str) -> None:
        shutil.rmtree(self.session_dir(sid), ignore_errors=True)
