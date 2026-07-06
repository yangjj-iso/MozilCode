from __future__ import annotations

import pytest

from mozilcode.a2a.protocol import (
    A2AError,
    configuration_from_params,
    parse_json_rpc_request,
    parse_message_request,
    should_wait,
    task_id_from_params,
)


def test_parse_json_rpc_request_defaults_missing_params_to_object() -> None:
    request = parse_json_rpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tasks/list"}
    )

    assert request.id == 1
    assert request.method == "tasks/list"
    assert request.params == {}


def test_parse_message_request_accepts_direct_content_and_metadata_aliases() -> None:
    request = parse_message_request(
        {
            "content": "  hello  ",
            "context_id": "ctx-1",
            "task_id": "task-1",
            "metadata": {"workDir": "D:/work", "ticket": "T-1"},
        }
    )

    assert request.prompt == "hello"
    assert request.context_id == "ctx-1"
    assert request.task_id_hint == "task-1"
    assert request.work_dir == "D:/work"
    assert request.metadata == {"workDir": "D:/work", "ticket": "T-1"}


def test_task_id_from_params_accepts_string_and_aliases() -> None:
    assert task_id_from_params(" task-1 ") == "task-1"
    assert task_id_from_params({"taskId": " task-2 "}) == "task-2"


def test_configuration_wait_flags_keep_existing_precedence() -> None:
    config = configuration_from_params(
        {
            "configuration": {
                "returnImmediately": True,
                "blocking": True,
            }
        }
    )

    assert should_wait(config) is False


def test_protocol_errors_keep_a2a_codes() -> None:
    with pytest.raises(A2AError) as exc:
        parse_message_request({"metadata": "bad", "content": "hello"})

    assert exc.value.code == -32602
    assert exc.value.message == "metadata must be an object"
