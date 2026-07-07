from __future__ import annotations

import pytest

from mozilcode.agent import CompactNotification, ErrorEvent
from mozilcode.context import compute_compact_threshold
from mozilcode.daemon.compact_actions import run_manual_compact
from mozilcode.daemon.responses import DaemonActionResult


class _Conversation:
    def __init__(self, tokens: int = 42_000) -> None:
        self.tokens = tokens

    def current_tokens(self) -> int:
        return self.tokens


class _Agent:
    context_window = 128_000
    total_input_tokens = 11
    total_output_tokens = 7

    def __init__(self, result) -> None:
        self.result = result

    async def manual_compact(self, _conversation):
        return self.result


@pytest.mark.asyncio
async def test_run_manual_compact_emits_started_result_usage_and_status() -> None:
    events: list[dict | None] = []
    persisted: list[str] = []

    result = await run_manual_compact(
        sid="sid",
        agent=_Agent(CompactNotification(42_000, "done", 8_000)),
        conversation=_Conversation(),
        emit_event=lambda _sid, event: events.append(event),
        persist_events=persisted.append,
        status_provider=lambda sid: {"id": sid, "ready": True},
    )

    assert result.status_code == 200
    assert result.payload["type"] == "CompactNotification"
    assert result.payload["status"] == {"id": "sid", "ready": True}
    assert persisted == ["sid"]
    assert [event["type"] for event in events if event is not None] == [
        "CompactStarted",
        "CompactNotification",
        "UsageEvent",
    ]
    assert events[0] is not None
    assert events[0]["data"]["threshold"] == max(
        0,
        compute_compact_threshold(128_000, manual=True),
    )
    assert events[2] is not None
    assert events[2]["data"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "context_tokens": 42_000,
    }


@pytest.mark.asyncio
async def test_run_manual_compact_error_skips_usage_and_status() -> None:
    events: list[dict | None] = []
    persisted: list[str] = []
    status_called = False

    def status_provider(_sid: str) -> dict:
        nonlocal status_called
        status_called = True
        return {}

    result = await run_manual_compact(
        sid="sid",
        agent=_Agent(ErrorEvent("compact failed")),
        conversation=_Conversation(),
        emit_event=lambda _sid, event: events.append(event),
        persist_events=persisted.append,
        status_provider=status_provider,
    )

    assert result == DaemonActionResult({"error": "compact failed"}, status_code=400)
    assert persisted == ["sid"]
    assert status_called is False
    assert [event["type"] for event in events if event is not None] == [
        "CompactStarted",
        "ErrorEvent",
    ]
