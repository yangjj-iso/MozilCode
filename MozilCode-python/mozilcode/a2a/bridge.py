from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any


TASK_SUBMITTED = "TASK_STATE_SUBMITTED"
TASK_WORKING = "TASK_STATE_WORKING"
TASK_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
TASK_COMPLETED = "TASK_STATE_COMPLETED"
TASK_FAILED = "TASK_STATE_FAILED"
TASK_CANCELED = "TASK_STATE_CANCELED"

TERMINAL_STATES = {TASK_COMPLETED, TASK_FAILED, TASK_CANCELED}


class A2AError(Exception):
    def __init__(self, message: str, code: int = -32000, data: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data


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


class A2ABridge:
    """Expose the daemon Agent as a small A2A-compatible task bridge.

    The bridge deliberately reuses the daemon's existing session/task/event-log
    surface. A2A and chat transports remain protocol adapters; the Agent loop
    stays unchanged.
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
            return [await self._handle_json_rpc_single(item) for item in payload]
        return await self._handle_json_rpc_single(payload)

    async def _handle_json_rpc_single(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self._json_error(None, -32600, "Invalid JSON-RPC request")

        req_id = payload.get("id")
        method = str(payload.get("method") or "")
        params = payload.get("params") or {}

        try:
            result = await self._dispatch(method, params)
        except A2AError as e:
            return self._json_error(req_id, e.code, e.message, e.data)
        except Exception as e:
            return self._json_error(req_id, -32000, str(e))

        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    async def _dispatch(self, method: str, params: Any) -> Any:
        normalized = method.strip()
        if normalized in {"message/send", "SendMessage", "Message/Send"}:
            if not isinstance(params, dict):
                raise A2AError("message/send params must be an object", -32602)
            return await self.send_message(params)
        if normalized in {"tasks/get", "GetTask", "Task/Get"}:
            task_id = _task_id_from_params(params)
            return self.task_to_a2a(self.get_task(task_id))
        if normalized in {"tasks/cancel", "CancelTask", "Task/Cancel"}:
            task_id = _task_id_from_params(params)
            return self.task_to_a2a(await self.cancel_task(task_id))
        if normalized in {"tasks/list", "ListTasks", "Task/List"}:
            return {"tasks": [self.task_to_a2a(t) for t in self._tasks.values()]}
        if normalized in {"agent/getAuthenticatedExtendedCard", "GetAgentCard"}:
            return self.agent_card()
        raise A2AError(f"Unsupported A2A method: {method}", -32601)

    async def send_message(self, params: dict[str, Any]) -> dict[str, Any]:
        task = await self.start_task_from_message(params, source="a2a")
        if _should_wait(params):
            timeout = _float_from_config(params, "timeout", self._default_wait_timeout)
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

    async def start_task_from_message(self, params: dict[str, Any], source: str) -> A2ATask:
        message = params.get("message") or params
        if not isinstance(message, dict):
            raise A2AError("message must be an object", -32602)

        prompt = _extract_text(message)
        if not prompt:
            raise A2AError("message must contain a text part", -32602)

        context_id = (
            message.get("contextId")
            or message.get("context_id")
            or params.get("contextId")
            or params.get("context_id")
        )
        task_id_hint = message.get("taskId") or message.get("task_id") or params.get("taskId") or params.get("task_id")
        if not context_id and task_id_hint and task_id_hint in self._tasks:
            context_id = self._tasks[task_id_hint].context_id
        context_id = str(context_id or f"ctx-{uuid.uuid4().hex[:12]}")

        metadata = dict(params.get("metadata") or {})
        work_dir = metadata.get("work_dir") or metadata.get("workDir")
        session_id = self._contexts.get(context_id)
        if session_id is None:
            try:
                session_id = await self._server.init_session(work_dir=work_dir)
            except ValueError as e:
                raise A2AError(str(e), -32001) from e
            self._contexts[context_id] = session_id

        log_list = self._server.get_event_log(session_id)
        start_cursor = len(log_list) if log_list is not None else 0
        try:
            internal_task_id = await self._server.start_task(session_id, prompt)
        except ValueError as e:
            raise A2AError(str(e), -32002) from e

        task_id = str(task_id_hint or internal_task_id or uuid.uuid4().hex[:8])
        if task_id in self._tasks:
            task_id = f"{task_id}-{uuid.uuid4().hex[:4]}"
        task = A2ATask(
            id=task_id,
            context_id=context_id,
            session_id=session_id,
            internal_task_id=internal_task_id,
            prompt=prompt,
            source=source,
            state=TASK_WORKING,
            cursor=start_cursor,
            metadata=metadata,
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
                task.state = TASK_CANCELED
                task.status_message = "Task cancellation requested."
                task.updated_at = _iso_now()
        return task

    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> A2ATask:
        task = self.get_task(task_id)
        deadline = time.monotonic() + (timeout if timeout is not None else self._default_wait_timeout)
        while task.state not in TERMINAL_STATES:
            if time.monotonic() >= deadline:
                task.status_message = "Timed out waiting for task completion."
                task.updated_at = _iso_now()
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
            "metadata": {
                "source": task.source,
                "session_id": task.session_id,
                "internal_task_id": task.internal_task_id,
                **task.metadata,
            },
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
                task.state = TASK_FAILED
                task.error = "Session disappeared."
                task.status_message = task.error
                task.updated_at = _iso_now()
            return

        if task.cursor > len(log_list):
            task.cursor = len(log_list)
            return

        for ev in log_list[task.cursor:]:
            if ev is None:
                task.state = TASK_FAILED
                task.error = "Session closed."
                task.status_message = task.error
                task.updated_at = _iso_now()
                continue
            if not isinstance(ev, dict):
                continue
            event_task_id = ev.get("task_id")
            if event_task_id and event_task_id != task.internal_task_id:
                continue
            event_type = ev.get("type")
            data = ev.get("data") or {}
            if event_type == "StreamText":
                text = data.get("text", "")
                if text:
                    task.output_parts.append(str(text))
                    task.state = TASK_WORKING
                    task.updated_at = _iso_now()
            elif event_type == "ErrorEvent":
                task.state = TASK_FAILED
                task.error = str(data.get("message") or "Agent task failed.")
                task.status_message = task.error
                task.updated_at = _iso_now()
            elif event_type == "TaskCancelled":
                task.state = TASK_CANCELED
                task.status_message = str(data.get("message") or "Task cancelled.")
                task.updated_at = _iso_now()
            elif event_type in {"PermissionRequest", "AskUserRequest"}:
                if task.state not in TERMINAL_STATES:
                    task.state = TASK_INPUT_REQUIRED
                    task.status_message = "The task requires interactive input in the MozilCode UI."
                    task.updated_at = _iso_now()
            elif event_type == "LoopComplete":
                if task.state not in {TASK_FAILED, TASK_CANCELED}:
                    task.state = TASK_COMPLETED
                    task.status_message = ""
                    task.updated_at = _iso_now()
        task.cursor = len(log_list)

    def _json_error(self, req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _extract_text(message: dict[str, Any]) -> str:
    direct = message.get("content")
    if isinstance(direct, str):
        return direct.strip()

    parts = message.get("parts") or []
    if not isinstance(parts, list):
        return ""

    chunks: list[str] = []
    for part in parts:
        if isinstance(part, str):
            chunks.append(part)
            continue
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str):
            chunks.append(part["text"])
            continue
        nested = part.get("text")
        if isinstance(nested, dict) and isinstance(nested.get("text"), str):
            chunks.append(nested["text"])
            continue
        if isinstance(part.get("data"), str):
            chunks.append(part["data"])
    return "\n".join(c.strip() for c in chunks if c and c.strip()).strip()


def _task_id_from_params(params: Any) -> str:
    if isinstance(params, str):
        return params
    if not isinstance(params, dict):
        raise A2AError("task params must be an object", -32602)
    task_id = params.get("id") or params.get("taskId") or params.get("task_id")
    if not task_id:
        raise A2AError("task id is required", -32602)
    return str(task_id)


def _should_wait(params: dict[str, Any]) -> bool:
    config = params.get("configuration") or {}
    if not isinstance(config, dict):
        config = {}
    if "returnImmediately" in config:
        return not bool(config.get("returnImmediately"))
    if "blocking" in config:
        return bool(config.get("blocking"))
    if "waitUntilCompleted" in config:
        return bool(config.get("waitUntilCompleted"))
    return False


def _float_from_config(params: dict[str, Any], key: str, default: float) -> float:
    config = params.get("configuration") or {}
    if not isinstance(config, dict):
        return default
    value = config.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
