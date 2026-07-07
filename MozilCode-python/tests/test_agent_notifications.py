from __future__ import annotations

from dataclasses import dataclass

from mozilcode.agent_notifications import (
    consume_team_mailbox,
    format_mailbox_message,
    inject_external_notifications,
)
from mozilcode.conversation import ConversationManager


@dataclass
class DummyMessage:
    from_agent: str
    content: str
    message_type: str = "text"


class DummyMailbox:
    def __init__(self, messages: list[DummyMessage]) -> None:
        self.messages = messages
        self.consumed_agent_id = ""

    def consume(self, agent_id: str) -> list[DummyMessage]:
        self.consumed_agent_id = agent_id
        return self.messages


class DummyTeamManager:
    def __init__(self, mailbox: DummyMailbox | None) -> None:
        self.mailbox = mailbox
        self.requested_team = ""

    def get_mailbox(self, team_name: str) -> DummyMailbox | None:
        self.requested_team = team_name
        return self.mailbox


class FailingTeamManager:
    def get_mailbox(self, team_name: str) -> DummyMailbox:
        raise RuntimeError("mailbox unavailable")


def test_format_mailbox_message_uses_text_prefix() -> None:
    assert (
        format_mailbox_message(DummyMessage("alice", "hello"))
        == "[Message from alice] hello"
    )


def test_format_mailbox_message_includes_non_text_type() -> None:
    assert (
        format_mailbox_message(
            DummyMessage("alice", "please stop", "shutdown_request"),
        )
        == "[shutdown_request from alice] please stop"
    )


def test_consume_team_mailbox_adds_messages_to_conversation() -> None:
    mailbox = DummyMailbox(
        [
            DummyMessage("alice", "hello"),
            DummyMessage("bob", "stop", "shutdown_request"),
        ]
    )
    manager = DummyTeamManager(mailbox)
    conversation = ConversationManager()

    consume_team_mailbox(
        conversation,
        team_name="core",
        team_manager=manager,
        agent_id="lead-1",
    )

    messages = conversation.get_messages()
    assert manager.requested_team == "core"
    assert mailbox.consumed_agent_id == "lead-1"
    assert [message.content for message in messages] == [
        "[Message from alice] hello",
        "[shutdown_request from bob] stop",
    ]


def test_consume_team_mailbox_ignores_missing_team_context() -> None:
    conversation = ConversationManager()

    consume_team_mailbox(
        conversation,
        team_name="",
        team_manager=DummyTeamManager(None),
        agent_id="lead-1",
    )

    assert conversation.get_messages() == []


def test_consume_team_mailbox_isolates_team_manager_failure() -> None:
    conversation = ConversationManager()

    consume_team_mailbox(
        conversation,
        team_name="core",
        team_manager=FailingTeamManager(),
        agent_id="lead-1",
    )

    assert conversation.get_messages() == []


def test_inject_external_notifications_adds_system_reminders_after_mailbox() -> None:
    mailbox = DummyMailbox([DummyMessage("alice", "hello")])
    conversation = ConversationManager()

    inject_external_notifications(
        conversation,
        team_name="core",
        team_manager=DummyTeamManager(mailbox),
        agent_id="lead-1",
        notification_fn=lambda: ["note one", "note two"],
    )

    messages = conversation.get_messages()
    assert messages[0].content == "[Message from alice] hello"
    assert messages[1].content == (
        "<system-reminder>\nnote one\n</system-reminder>"
    )
    assert messages[2].content == (
        "<system-reminder>\nnote two\n</system-reminder>"
    )
