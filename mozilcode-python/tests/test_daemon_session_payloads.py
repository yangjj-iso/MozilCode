"""Daemon 会话相关 HTTP body 模型测试。"""

from __future__ import annotations

import pytest

from mozilcode.daemon.request_body import BodyFieldError
from mozilcode.daemon.session.payloads import (
    AskUserResolutionBody,
    CreateSessionBody,
    PermissionResolutionBody,
    StartTaskBody,
    parse_askuser_resolution_body,
    parse_create_session_body,
    parse_mode_body,
    parse_permission_resolution_body,
    parse_start_task_body,
)


def test_parse_create_session_body_normalizes_empty_fields() -> None:
    body = parse_create_session_body({"session_id": "", "work_dir": None})

    assert body == CreateSessionBody(session_id=None, work_dir=None)


def test_parse_mode_body_accepts_known_modes() -> None:
    assert parse_mode_body({"mode": "plan"}) == "plan"
    assert parse_mode_body({"mode": "do"}) == "do"


def test_parse_mode_body_rejects_unknown_mode() -> None:
    with pytest.raises(BodyFieldError, match="'mode' must be one of"):
        parse_mode_body({"mode": "cloud"})


def test_parse_start_task_body_requires_session_and_prompt() -> None:
    body = parse_start_task_body({"session_id": "sid", "prompt": "run tests"})

    assert body == StartTaskBody(session_id="sid", prompt="run tests")


def test_parse_permission_resolution_body_defaults_to_deny() -> None:
    body = parse_permission_resolution_body({"request_id": "req-1"})

    assert body == PermissionResolutionBody(request_id="req-1", response="deny")


def test_parse_askuser_resolution_body_preserves_string_answers() -> None:
    body = parse_askuser_resolution_body(
        {"request_id": "ask-1", "answers": {"choice": "yes"}}
    )

    assert body == AskUserResolutionBody(
        request_id="ask-1",
        answers={"choice": "yes"},
    )
