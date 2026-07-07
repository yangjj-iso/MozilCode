from __future__ import annotations

from pathlib import Path

from mozilcode.agent_recovery import record_tool_recovery_snapshot
from mozilcode.context import RecoveryState
from mozilcode.tools.base import ToolCallComplete, ToolResult


def test_record_tool_recovery_snapshot_uses_work_dir(tmp_path, monkeypatch) -> None:
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()
    monkeypatch.chdir(outside_cwd)
    (tmp_path / "note.txt").write_text("from work dir", encoding="utf-8")
    state = RecoveryState()

    record_tool_recovery_snapshot(
        recovery_state=state,
        tool_call=ToolCallComplete("t1", "ReadFile", {"file_path": "note.txt"}),
        result=ToolResult(output="1\tfrom work dir"),
        work_dir=str(tmp_path),
    )

    files = state.snapshot_files(1)
    assert len(files) == 1
    assert Path(files[0].path) == tmp_path / "note.txt"
    assert files[0].content == "from work dir"


def test_record_tool_recovery_snapshot_ignores_failed_results(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("content", encoding="utf-8")
    state = RecoveryState()

    record_tool_recovery_snapshot(
        recovery_state=state,
        tool_call=ToolCallComplete("t1", "ReadFile", {"file_path": "note.txt"}),
        result=ToolResult(output="error", is_error=True),
        work_dir=str(tmp_path),
    )

    assert state.snapshot_files(1) == []


def test_record_tool_recovery_snapshot_ignores_non_readfile_tool(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("content", encoding="utf-8")
    state = RecoveryState()

    record_tool_recovery_snapshot(
        recovery_state=state,
        tool_call=ToolCallComplete("t1", "WriteFile", {"file_path": "note.txt"}),
        result=ToolResult(output="ok"),
        work_dir=str(tmp_path),
    )

    assert state.snapshot_files(1) == []


def test_record_tool_recovery_snapshot_ignores_missing_file_path(tmp_path) -> None:
    state = RecoveryState()

    record_tool_recovery_snapshot(
        recovery_state=state,
        tool_call=ToolCallComplete("t1", "ReadFile", {}),
        result=ToolResult(output="ok"),
        work_dir=str(tmp_path),
    )

    assert state.snapshot_files(1) == []


def test_record_tool_recovery_snapshot_ignores_unreadable_path(tmp_path) -> None:
    state = RecoveryState()

    record_tool_recovery_snapshot(
        recovery_state=state,
        tool_call=ToolCallComplete("t1", "ReadFile", {"file_path": "missing.txt"}),
        result=ToolResult(output="ok"),
        work_dir=str(tmp_path),
    )

    assert state.snapshot_files(1) == []
