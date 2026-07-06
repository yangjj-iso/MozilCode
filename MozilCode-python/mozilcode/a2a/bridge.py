from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from mozilcode.a2a.protocol import (
    A2AError,
    configuration_from_params,
    float_from_config,
    parse_json_rpc_request,
    parse_message_request,
    should_wait,
    task_id_from_params,
)


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


def _package_version() -> str:
    try:
        return version("mozilcode")
    except PackageNotFoundError:
        return "0.2.0"


def _set_task_state(
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


def _event_applies_to_task(task: A2ATask, event: dict[str, Any]) -> bool:
    event_task_id = event.get("task_id")
    return not event_task_id or event_task_id == task.internal_task_id


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _apply_task_log_event(task: A2ATask, event: object) -> None:
    if task.state in TERMINAL_STATES:
        return
    if event is None:
        _set_task_state(
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
            _set_task_state(task, TASK_WORKING)
    elif event_type == "ErrorEvent":
        message = str(data.get("message") or "Agent task failed.")
        _set_task_state(
            task,
            TASK_FAILED,
            status_message=message,
            error=message,
        )
    elif event_type == "TaskCancelled":
        _set_task_state(
            task,
            TASK_CANCELED,
            status_message=str(data.get("message") or "Task cancelled."),
        )
    elif event_type in {"PermissionRequest", "AskUserRequest"}:
        if task.state not in TERMINAL_STATES:
            _set_task_state(
                task,
                TASK_INPUT_REQUIRED,
                status_message=(
                    "The task requires interactive input from a "
                    "MozilCode daemon client."
                ),
            )
    elif event_type == "LoopComplete":
        if task.state not in {TASK_FAILED, TASK_CANCELED}:
            _set_task_state(task, TASK_COMPLETED, status_message="")


def _task_metadata(task: A2ATask) -> dict[str, Any]:
    return {
        **task.metadata,
        "source": task.source,
        "session_id": task.session_id,
        "internal_task_id": task.internal_task_id,
    }


class A2ABridge:
    """Expose the daemon Agent as a small A2A-compatible task bridge.

    The bridge deliberately reuses the daemon's existing session/task/event-log
    surface. A2A remains a protocol adapter; the Agent loop stays unchanged.
    """

    def __init__(self, daemon_server: Any, default_wait_timeout: float = 120.0) -> None:
        self._server = daemon_server
        self._default_wait_timeout = default_wait_timeout
        self._tasks: dict[str, A2ATask] = {}
        self._contexts: dict[str, str] = {}

    def agent_card(self, base_url: str = "") -> dict[str, Any]:
        base = base_url.rstrip("/")
        endpoint = f"{base}/a2a/rpc" if base else "/a2a/rpc"
        model = ""
        if getattr(self._server, "config", None) is not None and self._server.config.providers:
            model = self._server.config.providers[0].model
        return {
            "protocolVersion": "1.0.0",
            "name": "MozilCode",
            "description": "Local MozilCode coding agent exposed through A2A.",
            "url": endpoint,
            "preferredTransport": "JSONRPC",
            "additionalInterfaces": [
                {"transport": "JSONRPC", "url": endpoint},
            ],
            "provider": {"organization": "MozilCode"},
            "version": _package_version(),
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitionHistory": True,
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [
                {
                    "id": "coding",
                    "name": "Coding Agent",
                    "description": "Answer software engineering questions and modify local workspaces.",
                    "tags": ["coding", "software-development", "terminal-agent"],
                    "inputModes": ["text/plain"],
                    "outputModes": ["text/plain"],
                }
            ],
            "metadata": {
                "work_dir": getattr(self._server, "work_dir", ""),
                "model": model,
            },
        }

    async def handle_json_rpc(self, payload: Any) -> Any:
        if isinstance(payload, list):
            if not payload:
                return self._json_error(None, -32600, "Invalid JSON-RPC request")
            return [await self._handle_json_rpc_single(item) for item in payload]
        return await self._handle_json_rpc_single(payload)

    async def _handle_json_rpc_single(self, payload: Any) -> dict[str, Any]:
        try:
            request = parse_json_rpc_request(payload)
        except A2AError as e:
            req_id = payload.get("id") if isinstance(payload, dict) else None
            return self._json_error(req_id, e.code, e.message, e.data)

        try:
            result = await self._dispatch(request.method, request.params)
        except A2AError as e:
            return self._json_error(request.id, e.code, e.message, e.data)
        except Exception as e:
            return self._json_error(request.id, -32000, str(e))

        return {"jsonrpc": "2.0", "id": request.id, "result": result}

    async def _dispatch(self, method: str, params: Any) -> Any:
        normalized = method.strip()
        if normalized in {"message/send", "SendMessage", "Message/Send"}:
            if not isinstance(params, dict):
                raise A2AError("message/send params must be an object", -32602)
            return await self.send_message(params)
        if normalized in {"tasks/get", "GetTask", "Task/Get"}:
            task_id = task_id_from_params(params)
            return self.task_to_a2a(self.get_task(task_id))
        if normalized in {"tasks/cancel", "CancelTask", "Task/Cancel"}:
            task_id = task_id_from_params(params)
            return self.task_to_a2a(await self.cancel_task(task_id))
        if normalized in {"tasks/list", "ListTasks", "Task/List"}:
            return {"tasks": [self.task_to_a2a(t) for t in self._tasks.values()]}
        if normalized in {"agent/getAuthenticatedExtendedCard", "GetAgentCard"}:
            return self.agent_card()
        raise A2AError(f"Unsupported A2A method: {method}", -32601)

    async def send_message(self, params: dict[str, Any]) -> dict[str, Any]:
        config = configuration_from_params(params)
        wait_for_completion = should_wait(config)
        timeout = (
            float_from_config(config, "timeout", self._default_wait_timeout)
            if wait_for_completion
            else None
        )
        task = await self.start_task_from_message(params, source="a2a")
        if wait_for_completion:
            await self.wait_for_task(task.id, timeout=timeout)
        else:
            self._refresh_task_from_log(task)
        return self.task_to_a2a(task)

    async def run_text(
        self,
        text: str,
        *,
        context_id: str | None = None,
        source: str = "a2a",
        metadata: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> A2ATask:
        params = {
            "message": {
                "role": "ROLE_USER",
                "messageId": uuid.uuid4().hex,
                "contextId": context_id,
                "parts": [{"kind": "text", "text": text}],
            },
            "metadata": metadata or {},
            "configuration": {"returnImmediately": False},
        }
        task = await self.start_task_from_message(params, source=source)
        await self.wait_for_task(task.id, timeout=timeout or self._default_wait_timeout)
        return task

    async def start_task_from_message(
        self,
        params: dict[str, Any],
        source: str,
    ) -> A2ATask:
        request = parse_message_request(params)
        context_id = request.context_id
        if (
            not context_id
            and request.task_id_hint
            and request.task_id_hint in self._tasks
        ):
            context_id = self._tasks[request.task_id_hint].context_id
        context_id = str(context_id or f"ctx-{uuid.uuid4().hex[:12]}")

        session_id = self._contexts.get(context_id)
        if session_id is None:
            try:
                session_id = await self._server.init_session(
                    work_dir=request.work_dir
                )
            except ValueError as e:
                raise A2AError(str(e), -32001) from e
            self._contexts[context_id] = session_id

        log_list = self._server.get_event_log(session_id)
        start_cursor = len(log_list) if log_list is not None else 0
        try:
            internal_task_id = await self._server.start_task(
                session_id,
                request.prompt,
            )
        except ValueError as e:
            raise A2AError(str(e), -32002) from e

        task_id = str(
            request.task_id_hint
            or internal_task_id
            or uuid.uuid4().hex[:8]
        )
        if task_id in self._tasks:
            task_id = f"{task_id}-{uuid.uuid4().hex[:4]}"
        task = A2ATask(
            id=task_id,
            context_id=context_id,
            session_id=session_id,
            internal_task_id=internal_task_id,
            prompt=request.prompt,
            source=source,
            state=TASK_WORKING,
            cursor=start_cursor,
            metadata=request.metadata,
        )
        self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> A2ATask:
        task = self._tasks.get(task_id)
        if task is None:
            raise A2AError(f"Task not found: {task_id}", -32003)
        self._refresh_task_from_log(task)
        return task

    async def cancel_task(self, task_id: str) -> A2ATask:
        task = self.get_task(task_id)
        if task.state not in TERMINAL_STATES:
            cancelled = self._server.cancel_active_task(task.session_id)
            if cancelled:
                _set_task_state(
                    task,
                    TASK_CANCELED,
                    status_message="Task cancellation requested.",
                )
        return task

    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> A2ATask:
        task = self.get_task(task_id)
        deadline = time.monotonic() + (timeout if timeout is not None else self._default_wait_timeout)
        while task.state not in TERMINAL_STATES:
            if time.monotonic() >= deadline:
                _set_task_state(
                    task,
                    task.state,
                    status_message="Timed out waiting for task completion.",
                )
                return task
            await asyncio.sleep(0.05)
            self._refresh_task_from_log(task)
        return task

    def task_to_a2a(self, task: A2ATask) -> dict[str, Any]:
        self._refresh_task_from_log(task)
        status: dict[str, Any] = {
            "state": task.state,
            "timestamp": task.updated_at,
        }
        if task.status_message:
            status["message"] = {
                "role": "ROLE_AGENT",
                "parts": [{"kind": "text", "text": task.status_message}],
            }
        out: dict[str, Any] = {
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
            "metadata": _task_metadata(task),
        }
        if task.output:
            out["artifacts"] = [
                {
                    "artifactId": "response",
                    "name": "MozilCode response",
                    "parts": [{"kind": "text", "text": task.output}],
                }
            ]
        if task.error:
            out.setdefault("metadata", {})["error"] = task.error
        return out

    def _refresh_task_from_log(self, task: A2ATask) -> None:
        log_list = self._server.get_event_log(task.session_id)
        if log_list is None:
            if task.state not in TERMINAL_STATES:
                _set_task_state(
                    task,
                    TASK_FAILED,
                    status_message="Session disappeared.",
                    error="Session disappeared.",
                )
            return

        if task.cursor > len(log_list):
            task.cursor = len(log_list)
            return

        for ev in log_list[task.cursor:]:
            _apply_task_log_event(task, ev)
        task.cursor = len(log_list)

    def _json_error(
        self,
        req_id: Any,
        code: int,
        message: str,
        data: Any = None,
    ) -> dict[str, Any]:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": req_id, "error": err}
