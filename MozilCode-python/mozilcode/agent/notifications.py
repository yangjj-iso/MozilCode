from __future__ import annotations

import logging
from typing import Any, Callable

from mozilcode.conversation import ConversationManager

log = logging.getLogger(__name__)


def format_mailbox_message(message: Any) -> str:
    prefix = f"[Message from {message.from_agent}]"
    if message.message_type != "text":
        prefix = f"[{message.message_type} from {message.from_agent}]"
    return f"{prefix} {message.content}"


def consume_team_mailbox(
    conversation: ConversationManager,
    *,
    team_name: str,
    team_manager: Any,
    agent_id: str,
) -> None:
    if not team_name or not team_manager:
        return
    try:
        mailbox = team_manager.get_mailbox(team_name)
        if mailbox is None:
            return
        for message in mailbox.consume(agent_id):
            conversation.add_user_message(format_mailbox_message(message))
    except Exception as e:
        log.debug("Mailbox consumption failed: %s", e)


def inject_external_notifications(
    conversation: ConversationManager,
    *,
    team_name: str,
    team_manager: Any,
    agent_id: str,
    notification_fn: Callable[[], list[str]] | None,
) -> None:
    consume_team_mailbox(
        conversation,
        team_name=team_name,
        team_manager=team_manager,
        agent_id=agent_id,
    )
    if notification_fn:
        for note in notification_fn():
            conversation.add_system_reminder(note)
