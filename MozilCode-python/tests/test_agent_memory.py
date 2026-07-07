from __future__ import annotations

import pytest

from mozilcode.agent_memory import AgentMemoryBridge
from mozilcode.conversation import ConversationManager
from mozilcode.memory.providers import (
    MEMORY_EVENT_TURN_COMMITTED,
    MemoryEvent,
    MemoryScope,
)


class RecordingMemoryHub:
    def __init__(self) -> None:
        self.load_calls: list[tuple[str, MemoryScope]] = []
        self.events: list[MemoryEvent] = []

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        self.load_calls.append((query, scope))
        return "remembered context"

    async def observe(self, event: MemoryEvent) -> None:
        self.events.append(event)


class FailingMemoryHub:
    async def observe(self, event: MemoryEvent) -> None:
        raise RuntimeError("memory backend down")


@pytest.mark.asyncio
async def test_agent_memory_bridge_load_context_builds_agent_scope(tmp_path) -> None:
    hub = RecordingMemoryHub()
    bridge = AgentMemoryBridge(
        memory_hub=hub,
        client=object(),
        protocol="anthropic",
        project_root=str(tmp_path),
    )

    context = await bridge.load_context("find this", session_id="session-1")

    assert context == "remembered context"
    assert len(hub.load_calls) == 1
    query, scope = hub.load_calls[0]
    assert query == "find this"
    assert scope.query == "find this"
    assert scope.session_id == "session-1"
    assert scope.project_root == str(tmp_path)
    assert scope.source == "agent"


@pytest.mark.asyncio
async def test_agent_memory_bridge_observe_builds_agent_event() -> None:
    hub = RecordingMemoryHub()
    client = object()
    conversation = ConversationManager()
    bridge = AgentMemoryBridge(
        memory_hub=hub,
        client=client,
        protocol="openai",
        project_root="D:/repo",
    )

    await bridge.observe(
        conversation,
        "turn_completed",
        session_id="session-2",
        agent_id="agent-1",
        query="latest request",
    )

    assert len(hub.events) == 1
    event = hub.events[0]
    assert event.type == "turn_completed"
    assert event.source == "agent"
    assert event.session_id == "session-2"
    assert event.query == "latest request"
    assert event.conversation is conversation
    assert event.client is client
    assert event.protocol == "openai"
    assert event.metadata == {"agent_id": "agent-1"}


@pytest.mark.asyncio
async def test_agent_memory_bridge_extract_uses_turn_committed_and_blocks_reentry() -> None:
    hub = RecordingMemoryHub()
    bridge = AgentMemoryBridge(
        memory_hub=hub,
        client=object(),
        protocol="anthropic",
        project_root="D:/repo",
    )
    conversation = ConversationManager()

    await bridge.extract_memories(
        conversation,
        session_id="session-3",
        agent_id="agent-2",
        query="summarize this",
    )

    assert len(hub.events) == 1
    assert hub.events[0].type == MEMORY_EVENT_TURN_COMMITTED
    assert bridge._extracting is False

    bridge._extracting = True
    await bridge.extract_memories(
        conversation,
        session_id="session-3",
        agent_id="agent-2",
        query="summarize this",
    )

    assert len(hub.events) == 1


@pytest.mark.asyncio
async def test_agent_memory_bridge_observe_isolates_backend_failure() -> None:
    bridge = AgentMemoryBridge(
        memory_hub=FailingMemoryHub(),
        client=object(),
        protocol="anthropic",
        project_root="D:/repo",
    )

    await bridge.observe(
        ConversationManager(),
        "turn_completed",
        session_id="session-4",
        agent_id="agent-3",
        query="latest",
    )
