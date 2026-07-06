from __future__ import annotations

import json

from mozilcode.daemon.responses import (
    DaemonActionResult,
    action_response,
    error_response,
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
