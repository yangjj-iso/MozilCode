from __future__ import annotations

from mozilcode.daemon.session.meta import (
    new_session_meta,
    session_info_from_meta,
    session_work_dir_from_meta,
    sort_session_ids_by_created_at,
)


def test_new_session_meta_sets_defaults() -> None:
    meta = new_session_meta("/workspace", created_at=123.5)

    assert meta == {
        "work_dir": "/workspace",
        "created_at": 123.5,
        "title": "",
    }


def test_session_info_from_meta_falls_back_for_missing_or_invalid_fields() -> None:
    assert session_info_from_meta(
        "sid-1",
        {"work_dir": "", "title": []},
        "/server",
    ) == {
        "id": "sid-1",
        "work_dir": "/server",
        "title": "",
    }


def test_session_work_dir_from_meta_uses_server_default_when_blank() -> None:
    assert session_work_dir_from_meta({"work_dir": ""}, "/server") == "/server"
    assert session_work_dir_from_meta({"work_dir": "/work"}, "/server") == "/work"


def test_sort_session_ids_by_created_at_descending_with_invalid_values_last() -> None:
    ordered = sort_session_ids_by_created_at(
        ["old", "missing", "new", "bad"],
        {
            "old": {"created_at": 10},
            "new": {"created_at": 30},
            "bad": {"created_at": True},
        },
    )

    assert ordered == ["new", "old", "missing", "bad"]
