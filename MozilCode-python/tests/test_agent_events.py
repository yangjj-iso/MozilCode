from __future__ import annotations

import mozilcode.agent as agent_module
from mozilcode.agent.events import PermissionResponse, StreamText, UsageEvent
from mozilcode.daemon.serialize import serialize_event


def test_agent_reexports_event_types_for_compatibility() -> None:
    assert agent_module.StreamText is StreamText
    assert agent_module.PermissionResponse is PermissionResponse


def test_agent_event_module_serializes_without_importing_agent_loop() -> None:
    assert serialize_event(StreamText("hello")) == {
        "type": "StreamText",
        "task_id": "",
        "data": {"text": "hello"},
    }
    assert serialize_event(UsageEvent(1, 2, context_tokens=3)) == {
        "type": "UsageEvent",
        "task_id": "",
        "data": {
            "input_tokens": 1,
            "output_tokens": 2,
            "context_tokens": 3,
        },
    }
