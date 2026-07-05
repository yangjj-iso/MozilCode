from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.a2a.bridge import A2ABridge, TASK_COMPLETED
from mozilcode.a2a.qq_official import OfficialQQAdapter, OfficialQQConfig
from mozilcode.a2a.telegram_official import TelegramBotAdapter, TelegramBotConfig
from mozilcode.config import AppConfig, ProviderConfig


class _FakeDaemon:
    def __init__(self) -> None:
        self.work_dir = "."
        self.config = AppConfig(
            providers=[
                ProviderConfig(
                    name="test",
                    protocol="openai",
                    base_url="http://127.0.0.1:8080/v1",
                    model="test-model",
                )
            ]
        )
        self.logs: dict[str, list[dict | None]] = {}
        self.sessions: list[str] = []
        self._task_counter = 0

    async def init_session(self, work_dir=None):
        sid = f"session-{len(self.sessions) + 1}"
        self.sessions.append(sid)
        self.logs[sid] = []
        return sid

    def get_event_log(self, sid):
        return self.logs.get(sid)

    async def start_task(self, sid, prompt):
        self._task_counter += 1
        task_id = f"task-{self._task_counter}"
        self.logs[sid].append({"type": "UserMessage", "task_id": task_id, "data": {"content": prompt}})
        self.logs[sid].append({"type": "StreamText", "task_id": task_id, "data": {"text": "echo: "}})
        self.logs[sid].append({"type": "StreamText", "task_id": task_id, "data": {"text": prompt}})
        self.logs[sid].append({"type": "LoopComplete", "task_id": task_id, "data": {}})
        return task_id

    def cancel_active_task(self, sid):
        self.logs[sid].append({"type": "TaskCancelled", "task_id": "task-x", "data": {}})
        return True


@pytest.mark.asyncio
async def test_a2a_message_send_waits_and_collects_text():
    bridge = A2ABridge(_FakeDaemon(), default_wait_timeout=1)

    result = await bridge.send_message({
        "message": {
            "messageId": "m1",
            "contextId": "ctx-1",
            "parts": [{"kind": "text", "text": "hello"}],
        },
        "configuration": {"returnImmediately": False},
    })

    assert result["status"]["state"] == TASK_COMPLETED
    assert result["contextId"] == "ctx-1"
    assert result["artifacts"][0]["parts"][0]["text"] == "echo: hello"


@pytest.mark.asyncio
async def test_a2a_json_rpc_send_and_get_task():
    bridge = A2ABridge(_FakeDaemon(), default_wait_timeout=1)

    send = await bridge.handle_json_rpc({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "m1",
                "parts": [{"kind": "text", "text": "rpc"}],
            },
            "configuration": {"returnImmediately": False},
        },
    })
    task_id = send["result"]["id"]

    get = await bridge.handle_json_rpc({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tasks/get",
        "params": {"id": task_id},
    })

    assert get["result"]["id"] == task_id
    assert get["result"]["status"]["state"] == TASK_COMPLETED


class _StubBridge:
    async def run_text(self, text, **kwargs):
        return SimpleNamespace(state=TASK_COMPLETED, output=f"ok: {text}", status_message="", error="")


class _StubOfficialQQApi:
    def __init__(self) -> None:
        self.posts = []

    async def post_json(self, path, payload):
        self.posts.append((path, payload))
        return {"id": "reply-1"}


class _StubTelegramApi:
    def __init__(self) -> None:
        self.messages = []

    async def send_message(self, chat_id, text, *, reply_to_message_id=None):
        self.messages.append((chat_id, text, reply_to_message_id))
        return {"result": {"message_id": 10}}


@pytest.mark.asyncio
async def test_official_qq_c2c_replies_with_msg_id():
    api = _StubOfficialQQApi()
    adapter = OfficialQQAdapter(
        _StubBridge(),
        api=api,
        config=OfficialQQConfig(command_prefix="/mew", timeout=1),
    )

    result = await adapter.handle_dispatch(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg-1",
            "author": {"user_openid": "user-openid"},
            "content": "/mew 你好",
        },
        background=False,
    )

    assert result == {"status": "accepted"}
    assert api.posts == [
        (
            "/v2/users/user-openid/messages",
            {"content": "ok: 你好", "msg_type": 0, "msg_seq": 1, "msg_id": "msg-1"},
        )
    ]


@pytest.mark.asyncio
async def test_official_qq_group_at_accepts_plain_content():
    api = _StubOfficialQQApi()
    adapter = OfficialQQAdapter(
        _StubBridge(),
        api=api,
        config=OfficialQQConfig(command_prefix="/mew", timeout=1),
    )

    result = await adapter.handle_dispatch(
        "GROUP_AT_MESSAGE_CREATE",
        {
            "id": "msg-2",
            "author": {"member_openid": "member-openid"},
            "group_openid": "group-openid",
            "content": " 你好",
        },
        background=False,
    )

    assert result == {"status": "accepted"}
    assert api.posts[0] == (
        "/v2/groups/group-openid/messages",
        {"content": "ok: 你好", "msg_type": 0, "msg_seq": 1, "msg_id": "msg-2"},
    )


@pytest.mark.asyncio
async def test_official_qq_group_full_message_requires_prefix():
    api = _StubOfficialQQApi()
    adapter = OfficialQQAdapter(
        _StubBridge(),
        api=api,
        config=OfficialQQConfig(command_prefix="/mew", timeout=1),
    )

    result = await adapter.handle_dispatch(
        "GROUP_MESSAGE_CREATE",
        {
            "id": "msg-3",
            "author": {"member_openid": "member-openid"},
            "group_openid": "group-openid",
            "content": "你好",
        },
        background=False,
    )

    assert result == {"status": "ignored"}
    assert api.posts == []


@pytest.mark.asyncio
async def test_telegram_private_strips_command_prefix():
    api = _StubTelegramApi()
    adapter = TelegramBotAdapter(
        _StubBridge(),
        api=api,
        config=TelegramBotConfig(command_prefix="/mew", timeout=1),
    )

    result = await adapter.handle_update(
        {
            "update_id": 1,
            "message": {
                "message_id": 11,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42, "username": "alice"},
                "text": "/mew 你好",
            },
        },
        background=False,
    )

    assert result == {"status": "accepted"}
    assert api.messages == [("42", "ok: 你好", 11)]


@pytest.mark.asyncio
async def test_telegram_group_requires_prefix():
    api = _StubTelegramApi()
    adapter = TelegramBotAdapter(
        _StubBridge(),
        api=api,
        config=TelegramBotConfig(command_prefix="/mew", timeout=1),
        bot_username="mozil_bot",
    )

    result = await adapter.handle_update(
        {
            "update_id": 2,
            "message": {
                "message_id": 12,
                "chat": {"id": -100, "type": "supergroup"},
                "from": {"id": 42},
                "text": "你好",
            },
        },
        background=False,
    )

    assert result == {"status": "ignored"}
    assert api.messages == []


@pytest.mark.asyncio
async def test_telegram_group_accepts_bot_command_mention():
    api = _StubTelegramApi()
    adapter = TelegramBotAdapter(
        _StubBridge(),
        api=api,
        config=TelegramBotConfig(command_prefix="/mew", timeout=1),
        bot_username="mozil_bot",
    )

    result = await adapter.handle_update(
        {
            "update_id": 3,
            "message": {
                "message_id": 13,
                "chat": {"id": -100, "type": "group"},
                "from": {"id": 42},
                "text": "/mew@mozil_bot 你好",
            },
        },
        background=False,
    )

    assert result == {"status": "accepted"}
    assert api.messages == [("-100", "ok: 你好", 13)]
