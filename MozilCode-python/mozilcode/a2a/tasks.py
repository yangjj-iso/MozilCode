from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


TASK_SUBMITTED = "TASK_STATE_SUBMITTED"
TASK_WORKING = "TASK_STATE_WORKING"
TASK_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
TASK_COMPLETED = "TASK_STATE_COMPLETED"
TASK_FAILED = "TASK_STATE_FAILED"
TASK_CANCELED = "TASK_STATE_CANCELED"

TERMINAL_STATES = {TASK_COMPLETED, TASK_FAILED, TASK_CANCELED}


@dataclass
class A2ATask:
    id: str
    context_id: str
    session_id: str
    internal_task_id: str
    prompt: str
    source: str = "a2a"
    state: str = TASK_SUBMITTED
    status_message: str = ""
    created_at: str = field(default_factory=lambda: _iso_now())
    updated_at: str = field(default_factory=lambda: _iso_now())
    cursor: int = 0
    output_parts: list[str] = field(default_factory=list)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def output(self) -> str:
        return "".join(self.output_parts).strip()


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def set_task_state(
    task: A2ATask,
    state: str,
    *,
    status_message: str | None = None,
    error: str | None = None,
) -> None:
    task.state = state
    if status_message is not None:
        task.status_message = status_message
    if error is not None:
        task.error = error
    task.updated_at = _iso_now()


def refresh_task_from_log(task: A2ATask, log_list: list[dict | None] | None) -> None:
    if log_list is None:
        if task.state not in TERMINAL_STATES:
            set_task_state(
                task,
                TASK_FAILED,
                status_message="Session disappeared.",
                error="Session disappeared.",
            )
        return

    if task.cursor > len(log_list):
        task.cursor = len(log_list)
        return

    for event in log_list[task.cursor:]:
        apply_task_log_event(task, event)
    task.cursor = len(log_list)


def apply_task_log_event(task: A2ATask, event: object) -> None:
    if task.state in TERMINAL_STATES:
        return
    if event is None:
        set_task_state(
            task,
            TASK_FAILED,
            status_message="Session closed.",
            error="Session closed.",
        )
        return
    if not isinstance(event, dict):
        return
    if not _event_applies_to_task(task, event):
        return

    event_type = event.get("type")
    data = _event_data(event)
    if event_type == "StreamText":
        text = data.get("text", "")
        if text:
            task.output_parts.append(str(text))
            set_task_state(task, TASK_WORKING)
    elif event_type == "ErrorEvent":
        message = str(data.get("message") or "Agent task failed.")
        set_task_state(
            task,
            TASK_FAILED,
            status_message=message,
            error=message,
        )
    elif event_type == "TaskCancelled":
        set_task_state(
            task,
            TASK_CANCELED,
            status_message=str(data.get("message") or "Task cancelled."),
        )
    elif event_type in {"PermissionRequest", "AskUserRequest"}:
        set_task_state(
            task,
            TASK_INPUT_REQUIRED,
            status_message=(
                "The task requires interactive input from a "
                "MozilCode daemon client."
            ),
        )
    elif event_type == "LoopComplete":
        set_task_state(task, TASK_COMPLETED, status_message="")


def task_to_a2a_payload(task: A2ATask) -> dict[str, Any]:
    status: dict[str, Any] = {
        "state": task.state,
        "timestamp": task.updated_at,
    }
    if task.status_message:
        status["message"] = {
            "role": "ROLE_AGENT",
            "parts": [{"kind": "text", "text": task.status_message}],
        }

    payload: dict[str, Any] = {
        "kind": "task",
        "id": task.id,
        "contextId": task.context_id,
        "status": status,
        "history": [
            {
                "role": "ROLE_USER",
                "parts": [{"kind": "text", "text": task.prompt}],
            }
        ],
        "metadata": task_metadata(task),
    }
    if task.output:
        payload["artifacts"] = [
            {
                "artifactId": "response",
                "name": "MozilCode response",
                "parts": [{"kind": "text", "text": task.output}],
            }
        ]
    if task.error:
        payload.setdefault("metadata", {})["error"] = task.error
    return payload


def task_metadata(task: A2ATask) -> dict[str, Any]:
    return {
        **task.metadata,
        "source": task.source,
        "session_id": task.session_id,
        "internal_task_id": task.internal_task_id,
    }


def _event_applies_to_task(task: A2ATask, event: dict[str, Any]) -> bool:
    event_task_id = event.get("task_id")
    return not event_task_id or event_task_id == task.internal_task_id


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}
