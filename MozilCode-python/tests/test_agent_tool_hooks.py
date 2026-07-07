from __future__ import annotations

import pytest

from mozilcode.agent_events import HookEvent
from mozilcode.agent_helpers import build_hook_context, infer_tool_file_path
from mozilcode.agent_tool_hooks import (
    build_tool_hook_context,
    run_post_tool_hook,
    run_pre_tool_hook,
)
from mozilcode.hooks import HookContext, ToolRejectedError
from mozilcode.tools.base import ToolCallComplete


class FakeHookEngine:
    def __init__(self, rejection: ToolRejectedError | None = None) -> None:
        self.rejection = rejection
        self.pre_contexts: list[HookContext] = []
        self.post_contexts: list[tuple[str, HookContext]] = []

    async def run_pre_tool_hooks(
        self,
        ctx: HookContext,
    ) -> ToolRejectedError | None:
        self.pre_contexts.append(ctx)
        return self.rejection

    async def run_hooks(self, event: str, ctx: HookContext) -> None:
        self.post_contexts.append((event, ctx))


def _tool_call() -> ToolCallComplete:
    return ToolCallComplete(
        "tool-1",
        "WriteFile",
        {"file_path": "src/app.py", "content": "x"},
    )


def _drain_events() -> list[HookEvent]:
    return [
        HookEvent(
            hook_id="hook-1",
            event="pre_tool_use",
            output="checked",
            success=True,
        )
    ]


def test_build_tool_hook_context_uses_tool_metadata_and_file_path() -> None:
    ctx = build_tool_hook_context(
        build_hook_context=build_hook_context,
        infer_file_path=infer_tool_file_path,
        event="pre_tool_use",
        tool_call=_tool_call(),
    )

    assert ctx.event_name == "pre_tool_use"
    assert ctx.tool_name == "WriteFile"
    assert ctx.tool_args == {"file_path": "src/app.py", "content": "x"}
    assert ctx.file_path == "src/app.py"


@pytest.mark.asyncio
async def test_run_pre_tool_hook_skips_missing_engine() -> None:
    result = await run_pre_tool_hook(
        hook_engine=None,
        build_hook_context=build_hook_context,
        drain_hook_events=_drain_events,
        tool_call=_tool_call(),
    )

    assert result.rejection is None
    assert result.events == []


@pytest.mark.asyncio
async def test_run_pre_tool_hook_returns_rejection_and_drained_events() -> None:
    rejection = ToolRejectedError("WriteFile", "blocked", "hook-1")
    engine = FakeHookEngine(rejection)

    result = await run_pre_tool_hook(
        hook_engine=engine,
        build_hook_context=build_hook_context,
        drain_hook_events=_drain_events,
        tool_call=_tool_call(),
    )

    assert result.rejection is rejection
    assert [event.hook_id for event in result.events] == ["hook-1"]
    assert engine.pre_contexts[0].event_name == "pre_tool_use"
    assert engine.pre_contexts[0].file_path == "src/app.py"


@pytest.mark.asyncio
async def test_run_post_tool_hook_runs_event_and_drains_events() -> None:
    engine = FakeHookEngine()

    events = await run_post_tool_hook(
        hook_engine=engine,
        build_hook_context=build_hook_context,
        drain_hook_events=_drain_events,
        tool_call=_tool_call(),
    )

    assert [event.hook_id for event in events] == ["hook-1"]
    assert len(engine.post_contexts) == 1
    event, ctx = engine.post_contexts[0]
    assert event == "post_tool_use"
    assert ctx.event_name == "post_tool_use"
    assert ctx.tool_name == "WriteFile"
    assert ctx.file_path == "src/app.py"


@pytest.mark.asyncio
async def test_run_post_tool_hook_skips_missing_engine() -> None:
    events = await run_post_tool_hook(
        hook_engine=None,
        build_hook_context=build_hook_context,
        drain_hook_events=_drain_events,
        tool_call=_tool_call(),
    )

    assert events == []
