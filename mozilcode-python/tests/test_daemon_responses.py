"""Daemon 统一响应/错误结果构造测试。"""

from __future__ import annotations

import json

from mozilcode.daemon.responses import (
    DaemonActionResult,
    action_result,
    action_response,
    bad_request_result,
    bad_request_response,
    error_result,
    error_response,
    not_found_result,
    not_found_response,
    session_not_found_result,
)


def _json_body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_action_response_uses_result_payload_and_status() -> None:
    response = action_response(DaemonActionResult({"ok": True}, status_code=202))

    assert response.status_code == 202
    assert _json_body(response) == {"ok": True}


def test_action_result_uses_payload_and_status() -> None:
    assert action_result({"ok": True}, status_code=202) == DaemonActionResult(
        {"ok": True},
        status_code=202,
    )


def test_error_result_includes_extra_fields() -> None:
    assert error_result("not configured", 400, configured=False) == DaemonActionResult(
        {"error": "not configured", "configured": False},
        status_code=400,
    )


def test_bad_request_result_uses_400() -> None:
    assert bad_request_result("mode is required") == DaemonActionResult(
        {"error": "mode is required"},
        status_code=400,
    )


def test_not_found_result_uses_404() -> None:
    assert not_found_result("session not found") == DaemonActionResult(
        {"error": "session not found"},
        status_code=404,
    )


def test_session_not_found_result_uses_stable_payload() -> None:
    assert session_not_found_result() == DaemonActionResult(
        {"error": "session not found"},
        status_code=404,
    )


def test_error_response_includes_extra_fields() -> None:
    response = error_response("not configured", 400, configured=False)

    assert response.status_code == 400
    assert _json_body(response) == {"error": "not configured", "configured": False}


def test_bad_request_response_uses_400() -> None:
    response = bad_request_response("mode is required")

    assert response.status_code == 400
    assert _json_body(response) == {"error": "mode is required"}


def test_not_found_response_uses_404() -> None:
    response = not_found_response("session not found")

    assert response.status_code == 404
    assert _json_body(response) == {"error": "session not found"}
