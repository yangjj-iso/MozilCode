from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mozilcode.hooks.conditions import ConditionGroup


_EXPANSION_RE = re.compile(
    r"\$(?P<name>EVENT|TOOL_NAME|FILE_PATH|MESSAGE|ERROR)"
    r"|\$TOOL_ARGS\.(?P<arg>[A-Za-z_][A-Za-z0-9_]*)"
)


@dataclass
class Action:
    type: str
    command: str = ""
    message: str = ""
    url: str = ""
    method: str = "POST"
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    prompt: str = ""
    timeout: int = 30


@dataclass
class ActionResult:
    output: str = ""
    success: bool = True


@dataclass
class Hook:
    id: str
    event: str
    action: Action
    condition: ConditionGroup | None = None
    reject: bool = False
    once: bool = False
    async_exec: bool = False
    executed: bool = False


    def should_run(self) -> bool:
        if self.once and self.executed:
            return False
        return True


    def mark_executed(self) -> None:
        self.executed = True


@dataclass
class HookContext:
    event_name: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    file_path: str = ""
    message: str = ""
    error: str = ""

    def get_field(self, name: str) -> str:
        if name == "tool":
            return self.tool_name
        if name == "event":
            return self.event_name
        if name.startswith("args."):
            key = name[5:]
            if key not in self.tool_args:
                return ""
            value = self.tool_args[key]
            return "" if value is None else str(value)
        return ""

    def expand(self, template: str) -> str:
        def replace(match: re.Match[str]) -> str:
            arg_key = match.group("arg")
            if arg_key is not None:
                if arg_key not in self.tool_args:
                    return match.group(0)
                value = self.tool_args[arg_key]
                return "" if value is None else str(value)

            name = match.group("name")
            if name == "EVENT":
                return self.event_name
            if name == "TOOL_NAME":
                return self.tool_name
            if name == "FILE_PATH":
                return self.file_path
            if name == "MESSAGE":
                return self.message
            if name == "ERROR":
                return self.error
            return match.group(0)

        return _EXPANSION_RE.sub(replace, template)


class ToolRejectedError(Exception):
    def __init__(self, tool: str, reason: str, hook_id: str) -> None:
        self.tool = tool
        self.reason = reason
        self.hook_id = hook_id
        super().__init__(f"Tool '{tool}' rejected by hook '{hook_id}': {reason}")
