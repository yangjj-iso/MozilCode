from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mozilcode.daemon.request_body import (
    choice_field,
    required_choice_field,
    required_string_field,
    string_field,
    string_mapping_field,
)

PERMISSION_RESPONSES = {"allow", "deny", "allow_always"}
MODE_REQUESTS = {
    "acceptEdits",
    "bypassPermissions",
    "custom",
    "default",
    "do",
    "dontAsk",
    "plan",
}


@dataclass(frozen=True)
class CreateSessionBody:
    session_id: str | None
    work_dir: str | None


@dataclass(frozen=True)
class StartTaskBody:
    session_id: str
    prompt: str


@dataclass(frozen=True)
class PermissionResolutionBody:
    request_id: str
    response: str


@dataclass(frozen=True)
class AskUserResolutionBody:
    request_id: str
    answers: dict[str, str]


def parse_create_session_body(body: dict[str, Any]) -> CreateSessionBody:
    return CreateSessionBody(
        session_id=string_field(body, "session_id") or None,
        work_dir=string_field(body, "work_dir") or None,
    )


def parse_mode_body(body: dict[str, Any]) -> str:
    return required_choice_field(body, "mode", MODE_REQUESTS)


def parse_start_task_body(body: dict[str, Any]) -> StartTaskBody:
    return StartTaskBody(
        session_id=required_string_field(body, "session_id"),
        prompt=required_string_field(body, "prompt"),
    )


def parse_permission_resolution_body(
    body: dict[str, Any],
) -> PermissionResolutionBody:
    return PermissionResolutionBody(
        request_id=required_string_field(body, "request_id"),
        response=choice_field(body, "response", PERMISSION_RESPONSES, "deny"),
    )


def parse_askuser_resolution_body(body: dict[str, Any]) -> AskUserResolutionBody:
    return AskUserResolutionBody(
        request_id=required_string_field(body, "request_id"),
        answers=string_mapping_field(body, "answers"),
    )
