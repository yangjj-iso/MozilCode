from __future__ import annotations

import json

from mozilcode.daemon.responses import (
    DaemonActionResult,
    action_response,
    bad_request_response,
    error_response,
    not_found_response,
)


def _json_body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_action_response_uses_result_payload_and_status() -> None:
    response = action_response(DaemonActionResult({"ok": True}, status_code=202))

    assert response.status_code == 202
    assert _json_body(response) == {"ok": True}


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
