from __future__ import annotations

import asyncio

import pytest

from mozilcode.daemon.pending_prompt_actions import resolve_session_pending_prompt
from mozilcode.daemon.pending_prompts import PendingPromptRegistry
from mozilcode.daemon.session import SessionManager


@pytest.mark.asyncio
async def test_resolve_session_pending_prompt_resolves_future_and_emits() -> None:
    session_mgr = SessionManager()
    pending_prompts = PendingPromptRegistry()
    events: list[tuple[str, dict | None]] = []
    session = await session_mgr.create_session("sid", object(), object())
    future = asyncio.get_running_loop().create_future()
    session.register_future("req-1", future)
    pending_prompts.record("sid", "req-1", {"type": "PermissionRequest"})

    ok = await resolve_session_pending_prompt(
        "sid",
        "req-1",
        "allow",
        "PermissionResolved",
        session_mgr=session_mgr,
        pending_prompts=pending_prompts,
        emit_event=lambda sid, event: events.append((sid, event)),
    )

    assert ok is True
    assert future.result() == "allow"
    assert pending_prompts.events("sid") == []
    assert events == [
        (
            "sid",
            {
                "type": "PermissionResolved",
                "data": {"request_id": "req-1"},
            },
        )
    ]


@pytest.mark.asyncio
async def test_resolve_session_pending_prompt_returns_false_for_missing_session() -> None:
    pending_prompts = PendingPromptRegistry()
    events: list[tuple[str, dict | None]] = []

    ok = await resolve_session_pending_prompt(
        "missing",
        "req-1",
        "allow",
        "PermissionResolved",
        session_mgr=SessionManager(),
        pending_prompts=pending_prompts,
        emit_event=lambda sid, event: events.append((sid, event)),
    )

    assert ok is False
    assert events == []


@pytest.mark.asyncio
async def test_resolve_session_pending_prompt_keeps_unmatched_pending_event() -> None:
    session_mgr = SessionManager()
    pending_prompts = PendingPromptRegistry()
    events: list[tuple[str, dict | None]] = []
    await session_mgr.create_session("sid", object(), object())
    pending_prompts.record("sid", "req-1", {"type": "AskUserRequest"})

    ok = await resolve_session_pending_prompt(
        "sid",
        "missing",
        {"answer": "yes"},
        "AskUserResolved",
        session_mgr=session_mgr,
        pending_prompts=pending_prompts,
        emit_event=lambda sid, event: events.append((sid, event)),
    )

    assert ok is False
    assert pending_prompts.events("sid") == [{"type": "AskUserRequest"}]
    assert events == []
