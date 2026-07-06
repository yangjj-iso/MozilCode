from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mozilcode.teams.fields import (
    non_negative_number_field,
    object_field,
    string_field,
)


MAILBOX_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VALID_MESSAGE_TYPES = {"text", "shutdown_request", "shutdown_response"}


def validate_mailbox_id(value: str, field_name: str = "agent_id") -> str:
    if not isinstance(value, str) or not MAILBOX_ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"{field_name} must be 1-64 characters of letters, digits, '_' or '-'"
        )
    return value


def _message_string_field(
    data: dict[str, Any],
    name: str,
    *,
    required: bool = True,
) -> str:
    return string_field(data, name, prefix="message", required=required)


@dataclass
class MailboxMessage:
    id: str
    from_agent: str
    to_agent: str
    content: str
    summary: str = ""
    message_type: str = "text"  # text | shutdown_request | shutdown_response
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MailboxMessage:
        if not isinstance(data, dict):
            raise ValueError("message must be an object")
        message_id = validate_mailbox_id(
            _message_string_field(data, "id"),
            "message.id",
        )
        message_type = (
            _message_string_field(data, "message_type", required=False) or "text"
        )
        if message_type not in VALID_MESSAGE_TYPES:
            raise ValueError(
                f"message.message_type must be one of: "
                f"{', '.join(sorted(VALID_MESSAGE_TYPES))}"
            )
        metadata = object_field(data, "metadata", prefix="message")
        return cls(
            id=message_id,
            from_agent=_message_string_field(data, "from_agent"),
            to_agent=_message_string_field(data, "to_agent"),
            content=_message_string_field(data, "content"),
            summary=_message_string_field(data, "summary", required=False),
            message_type=message_type,
            timestamp=non_negative_number_field(
                data,
                "timestamp",
                prefix="message",
            ),
            metadata=metadata,
        )


class Mailbox:
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def _agent_dir(self, agent_id: str) -> Path:
        return self._base_dir / validate_mailbox_id(agent_id)


    def write(self, agent_id: str, message: MailboxMessage) -> None:
        message = MailboxMessage.from_dict(message.to_dict())
        d = self._agent_dir(agent_id)
        d.mkdir(parents=True, exist_ok=True)
        filename = f"{message.timestamp:.6f}_{message.id}.json"
        (d / filename).write_text(
            json.dumps(message.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )

    def read(self, agent_id: str) -> list[MailboxMessage]:
        d = self._agent_dir(agent_id)
        if not d.exists():
            return []
        messages: list[MailboxMessage] = []
        for f in sorted(d.iterdir()):
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                messages.append(MailboxMessage.from_dict(data))
            except (json.JSONDecodeError, ValueError):
                continue
        return messages

    def consume(self, agent_id: str) -> list[MailboxMessage]:
        d = self._agent_dir(agent_id)
        if not d.exists():
            return []
        messages: list[MailboxMessage] = []
        for f in sorted(d.iterdir()):
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                messages.append(MailboxMessage.from_dict(data))
                f.unlink()
            except (json.JSONDecodeError, ValueError):
                continue
        return messages

    def broadcast(
        self,
        team_members: list[str],
        message: MailboxMessage,
        exclude: str = "",
    ) -> None:
        for agent_id in team_members:
            if agent_id == exclude:
                continue
            self.write(agent_id, message)


    def cleanup(self, agent_id: str) -> None:
        d = self._agent_dir(agent_id)
        if d.exists():
            for f in d.iterdir():
                f.unlink(missing_ok=True)
            d.rmdir()

    def cleanup_all(self) -> None:
        if not self._base_dir.exists():
            return
        for d in self._base_dir.iterdir():
            if d.is_dir():
                for f in d.iterdir():
                    f.unlink(missing_ok=True)
                d.rmdir()


def create_message(
    from_agent: str,
    to_agent: str,
    content: str,
    summary: str = "",
    message_type: str = "text",
    metadata: dict[str, Any] | None = None,
) -> MailboxMessage:
    return MailboxMessage(
        id=uuid.uuid4().hex[:12],
        from_agent=from_agent,
        to_agent=to_agent,
        content=content,
        summary=summary,
        message_type=message_type,
        timestamp=time.time(),
        metadata=metadata or {},
    )
