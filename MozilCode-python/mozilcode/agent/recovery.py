from __future__ import annotations

from mozilcode.context import RecoveryState
from mozilcode.tools.base import ToolCallComplete, ToolResult
from mozilcode.tools.paths import resolve_tool_path


def record_tool_recovery_snapshot(
    *,
    recovery_state: RecoveryState,
    tool_call: ToolCallComplete,
    result: ToolResult,
    work_dir: str,
) -> None:
    """Record ReadFile content that should survive Layer 2 compaction."""
    if result.is_error or tool_call.tool_name != "ReadFile":
        return
    path = (
        tool_call.arguments.get("file_path")
        if isinstance(tool_call.arguments, dict)
        else None
    )
    if not path:
        return
    resolved = resolve_tool_path(path, work_dir)
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return
    recovery_state.record_file_read(str(resolved), content)
