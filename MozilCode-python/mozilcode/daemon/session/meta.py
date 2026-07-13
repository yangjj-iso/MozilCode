from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from typing import Any


def new_session_meta(
    work_dir: str,
    *,
    provider_name: str = "",
    created_at: float | None = None,
) -> dict[str, Any]:
    meta = {
        "work_dir": work_dir,
        "created_at": time.time() if created_at is None else created_at,
        "title": "",
    }
    if provider_name:
        meta["provider_name"] = provider_name
    return meta


def session_info_from_meta(
    sid: str,
    meta: Mapping[str, Any] | None,
    server_work_dir: str,
) -> dict[str, str]:
    meta = meta or {}
    work_dir = meta.get("work_dir")
    title = meta.get("title")
    return {
        "id": sid,
        "work_dir": work_dir if isinstance(work_dir, str) and work_dir else server_work_dir,
        "title": title if isinstance(title, str) else "",
    }


def session_work_dir_from_meta(
    meta: Mapping[str, Any],
    server_work_dir: str,
) -> str:
    work_dir = meta.get("work_dir")
    return work_dir if isinstance(work_dir, str) and work_dir else server_work_dir


def sort_session_ids_by_created_at(
    sids: Iterable[str],
    session_meta: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    def created_at(sid: str) -> float:
        value = session_meta.get(sid, {}).get("created_at", 0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return 0.0

    return sorted(sids, key=created_at, reverse=True)
