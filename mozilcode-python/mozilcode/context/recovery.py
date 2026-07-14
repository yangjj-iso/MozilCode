"""压缩后恢复附件。

记录 ReadFile/技能等快照，压缩后写回工作集摘要。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping


# 追加到摘要 user 消息的恢复附件限制。compact 会清空工作对话；
# 没有这些快照，模型会忘记刚读过哪些文件、正在执行哪个 skill 的 SOP。
RECOVERY_FILE_LIMIT = 5
RECOVERY_TOKENS_PER_FILE = 5_000
RECOVERY_SKILLS_BUDGET = 25_000
RECOVERY_TOKENS_PER_SKILL = 5_000
_RECOVERY_CHARS_PER_TOKEN = 3.5


@dataclass
class FileReadRecord:
    path: str
    content: str
    timestamp: float


@dataclass
class SkillInvocationRecord:
    name: str
    body: str
    timestamp: float


class RecoveryState:
    """Per-agent context snapshots that survive Layer 2 compaction."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileReadRecord] = {}
        self._skills: dict[str, SkillInvocationRecord] = {}

    def record_file_read(self, path: str, content: str) -> None:
        if not path:
            return
        with self._lock:
            self._files[path] = FileReadRecord(
                path=path, content=content, timestamp=time.time()
            )

    def record_skill_invocation(self, name: str, body: str) -> None:
        if not name:
            return
        with self._lock:
            self._skills[name] = SkillInvocationRecord(
                name=name, body=body, timestamp=time.time()
            )

    def snapshot_files(self, limit: int) -> list[FileReadRecord]:
        with self._lock:
            records = list(self._files.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if limit > 0:
            records = records[:limit]
        return records

    def snapshot_skills(self) -> list[SkillInvocationRecord]:
        with self._lock:
            records = list(self._skills.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records


def _approx_tokens(s: str) -> int:
    if not s:
        return 0
    return int(len(s) / _RECOVERY_CHARS_PER_TOKEN)


def _truncate_by_tokens(s: str, token_budget: int) -> str:
    if token_budget <= 0 or not s:
        return s
    if _approx_tokens(s) <= token_budget:
        return s
    max_chars = int(token_budget * _RECOVERY_CHARS_PER_TOKEN)
    if max_chars <= 0 or max_chars >= len(s):
        return s
    return s[:max_chars] + "\n… (内容已截断)"


def _first_line(s: str) -> str:
    for line in s.split("\n"):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _tool_schema_summary(schema: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return a provider-agnostic ``(name, description)`` for a tool schema."""
    name = schema.get("name")
    desc = schema.get("description", "")

    nested = schema.get("function")
    if not name and isinstance(nested, Mapping):
        name = nested.get("name")
        desc = nested.get("description", desc)

    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(desc, str):
        desc = ""
    return name.strip(), _first_line(desc)


def build_recovery_attachment(
    state: RecoveryState | None,
    tool_schemas: list[Mapping[str, Any]] | None,
) -> str:
    """Render compact recovery context sections."""
    sections: list[str] = []

    if state is not None:
        files = state.snapshot_files(RECOVERY_FILE_LIMIT)
        if files:
            buf = [
                "## 最近读过的文件\n",
                "以下快照是文件读取工具上次返回的内容。如需当前字节请重新读取。\n",
            ]
            for rec in files:
                content = _truncate_by_tokens(rec.content, RECOVERY_TOKENS_PER_FILE)
                ts = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(rec.timestamp)
                )
                buf.append(f"### {rec.path}  (read {ts})\n")
                buf.append("```\n")
                buf.append(content)
                if not content.endswith("\n"):
                    buf.append("\n")
                buf.append("```\n")
            sections.append("".join(buf))

        skills = state.snapshot_skills()
        if skills:
            buf = [
                "## 已激活的技能\n",
                "下列技能在本会话中被调用过，其触发条件仍然适用。\n",
            ]
            used = 0
            emitted = False
            for sk in skills:
                body = _truncate_by_tokens(sk.body, RECOVERY_TOKENS_PER_SKILL)
                tokens = _approx_tokens(body) + _approx_tokens(sk.name) + 8
                if used + tokens > RECOVERY_SKILLS_BUDGET:
                    break
                used += tokens
                buf.append(f"### {sk.name}\n\n{body}\n")
                emitted = True
            if emitted:
                sections.append("".join(buf))

    if tool_schemas:
        buf = [
            "## 可用工具\n",
            "你仍然可以调用以下工具，需要时直接发起调用即可：\n",
        ]
        emitted = False
        for t in tool_schemas:
            if not isinstance(t, Mapping):
                continue
            summary = _tool_schema_summary(t)
            if summary is None:
                continue
            name, desc = summary
            if desc:
                buf.append(f"- {name} — {desc}\n")
            else:
                buf.append(f"- {name}\n")
            emitted = True
        if emitted:
            sections.append("".join(buf))

    if not sections:
        return ""

    sections.append(
        "## 提示\n\n以上恢复的上下文是重建的。若需要原文代码、错误信息或用户原话，"
        "请用文件读取工具重新读取，不要根据摘要猜测细节。\n"
    )
    return "\n".join(sections)
