"""会话记录序列化与 compact boundary。

Message ↔ 磁盘记录、压缩边界解析与消息链校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from mozilcode.conversation import Message, ToolResultBlock, ToolUseBlock


class RecordType(str, Enum):
    SYSTEM_PROMPT = "system_prompt"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    COMPRESSION = "compression"
    # Layer-2 compact 标记。auto_compact 压缩对话记录时写入。
    # 内容为结构化载荷（参见 make_compact_boundary / parse_compact_boundary），
    # 包含摘要文本和原样保留的 keep 尾部（以序列化 record 形式内联），
    # 使 resume 可以仅凭此标记重建压缩后的状态，无需重放标记之前的原始前缀。
    COMPACT_BOUNDARY = "compact_boundary"


def _record_from_mapping(
    data: object,
    *,
    timestamp_override: datetime | None = None,
) -> SessionRecord | None:
    if not isinstance(data, dict):
        return None
    raw_type = data.get("type")
    if not isinstance(raw_type, str):
        return None
    if "content" not in data:
        return None
    try:
        record_type = RecordType(raw_type)
    except ValueError:
        return None

    timestamp = timestamp_override
    if timestamp is None:
        raw_timestamp = data.get("timestamp")
        if not isinstance(raw_timestamp, str):
            return None
        try:
            timestamp = datetime.fromisoformat(raw_timestamp)
        except ValueError:
            return None

    tool_use_id = data.get("tool_use_id")
    if tool_use_id is not None and not isinstance(tool_use_id, str):
        return None
    is_error = data.get("is_error", False)
    if not isinstance(is_error, bool):
        return None

    return SessionRecord(
        type=record_type,
        content=data["content"],
        timestamp=timestamp,
        tool_use_id=tool_use_id,
        is_error=is_error,
    )


@dataclass
class SessionRecord:
    type: RecordType
    content: Any
    timestamp: datetime
    tool_use_id: str | None = None
    is_error: bool = False

    def to_jsonl(self) -> str:
        data: dict[str, Any] = {
            "type": self.type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.tool_use_id is not None:
            data["tool_use_id"] = self.tool_use_id
        if self.type == RecordType.TOOL_RESULT:
            data["is_error"] = self.is_error
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> SessionRecord | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None
        return _record_from_mapping(data)

    @classmethod
    def from_message(cls, message: Message) -> list[SessionRecord]:
        now = datetime.now(timezone.utc)
        records: list[SessionRecord] = []

        if message.tool_results:
            for tr in message.tool_results:
                records.append(
                    cls(
                        type=RecordType.TOOL_RESULT,
                        content=tr.content,
                        timestamp=now,
                        tool_use_id=tr.tool_use_id,
                        is_error=tr.is_error,
                    )
                )
        elif message.role == "assistant":
            if message.tool_uses:
                content_blocks: list[dict[str, Any]] = []
                if message.content:
                    content_blocks.append({"type": "text", "text": message.content})
                for tu in message.tool_uses:
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tu.tool_use_id,
                            "name": tu.tool_name,
                            "input": tu.arguments,
                        }
                    )
                records.append(
                    cls(type=RecordType.ASSISTANT, content=content_blocks, timestamp=now)
                )
            else:
                records.append(
                    cls(type=RecordType.ASSISTANT, content=message.content, timestamp=now)
                )
        else:
            records.append(
                cls(type=RecordType.USER, content=message.content, timestamp=now)
            )

        return records


def _message_to_record_dicts(message: Message) -> list[dict[str, Any]]:
    """Serialize one Message into inline record dictionaries."""
    dicts: list[dict[str, Any]] = []
    for rec in SessionRecord.from_message(message):
        data: dict[str, Any] = {"type": rec.type.value, "content": rec.content}
        if rec.tool_use_id is not None:
            data["tool_use_id"] = rec.tool_use_id
        if rec.type == RecordType.TOOL_RESULT:
            data["is_error"] = rec.is_error
        dicts.append(data)
    return dicts


def make_compact_boundary(summary: str, keep: list[Message]) -> SessionRecord:
    """Build a COMPACT_BOUNDARY record with summary and inline keep tail."""
    keep_dicts: list[dict[str, Any]] = []
    for msg in keep:
        keep_dicts.extend(_message_to_record_dicts(msg))
    payload = {"summary": summary, "keep": keep_dicts}
    return SessionRecord(
        type=RecordType.COMPACT_BOUNDARY,
        content=payload,
        timestamp=datetime.now(timezone.utc),
    )


def parse_compact_boundary(record: SessionRecord) -> tuple[str, list[Message]]:
    """Reverse make_compact_boundary into (summary, keep_messages)."""
    content = record.content
    if not isinstance(content, dict):
        return "", []
    raw_summary = content.get("summary", "")
    summary = raw_summary if isinstance(raw_summary, str) else ""
    keep_raw = content.get("keep", [])
    keep_records: list[SessionRecord] = []
    for item in keep_raw if isinstance(keep_raw, list) else []:
        keep_record = _record_from_mapping(item, timestamp_override=record.timestamp)
        if keep_record is not None:
            keep_records.append(keep_record)
    keep_records = truncate_to_valid_message_chain(keep_records)
    return summary, records_to_messages(keep_records)


def _tool_use_from_block(block: dict[str, Any]) -> ToolUseBlock | None:
    if block.get("type") != "tool_use":
        return None
    tool_id = block.get("id")
    tool_name = block.get("name")
    if not isinstance(tool_id, str) or not tool_id:
        return None
    if not isinstance(tool_name, str) or not tool_name:
        return None
    arguments = block.get("input", {})
    if not isinstance(arguments, dict):
        arguments = {}
    return ToolUseBlock(
        tool_use_id=tool_id,
        tool_name=tool_name,
        arguments=arguments,
    )


def _assistant_content_from_blocks(
    blocks: list[Any],
) -> tuple[str, list[ToolUseBlock]]:
    text = ""
    tool_uses: list[ToolUseBlock] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            block_text = block.get("text", "")
            if isinstance(block_text, str):
                text += block_text
            continue
        tool_use = _tool_use_from_block(block)
        if tool_use is not None:
            tool_uses.append(tool_use)
    return text, tool_uses


def records_to_messages(records: list[SessionRecord]) -> list[Message]:
    messages: list[Message] = []
    pending_tool_results: list[ToolResultBlock] = []

    for record in records:
        if record.type == RecordType.TOOL_RESULT:
            pending_tool_results.append(
                ToolResultBlock(
                    tool_use_id=record.tool_use_id or "",
                    content=(
                        record.content
                        if isinstance(record.content, str)
                        else json.dumps(record.content)
                    ),
                    is_error=record.is_error,
                )
            )
            continue

        if pending_tool_results:
            messages.append(
                Message(role="user", content="", tool_results=pending_tool_results)
            )
            pending_tool_results = []

        if record.type == RecordType.SYSTEM_PROMPT:
            continue

        if record.type == RecordType.COMPRESSION:
            messages.append(
                Message(
                    role="user",
                    content=(
                        "本次会话延续自之前的对话，因上下文空间不足进行了压缩。"
                        "以下是早期对话的摘要：\n\n"
                        + (record.content or "")
                    ),
                )
            )
            continue

        if record.type == RecordType.COMPACT_BOUNDARY:
            summary, keep_messages = parse_compact_boundary(record)
            messages.append(
                Message(
                    role="user",
                    content=(
                        "本次会话延续自之前的对话，因上下文空间不足进行了压缩。"
                        "以下是早期对话的摘要：\n\n"
                        + summary
                    ),
                )
            )
            messages.extend(keep_messages)
            continue

        if record.type == RecordType.USER:
            messages.append(Message(role="user", content=record.content or ""))
        elif record.type == RecordType.ASSISTANT:
            if isinstance(record.content, list):
                text, tool_uses = _assistant_content_from_blocks(record.content)
                messages.append(
                    Message(role="assistant", content=text, tool_uses=tool_uses)
                )
            else:
                messages.append(
                    Message(role="assistant", content=record.content or "")
                )

    if pending_tool_results:
        messages.append(
            Message(role="user", content="", tool_results=pending_tool_results)
        )

    return messages


def validate_message_chain(records: list[SessionRecord]) -> int:
    last_valid = 0
    pending_tool_uses: set[str] = set()

    for i, record in enumerate(records):
        if record.type == RecordType.ASSISTANT and isinstance(record.content, list):
            for block in record.content:
                if not isinstance(block, dict):
                    continue
                tool_use = _tool_use_from_block(block)
                if tool_use is not None:
                    pending_tool_uses.add(tool_use.tool_use_id)

        if record.type == RecordType.TOOL_RESULT and record.tool_use_id:
            pending_tool_uses.discard(record.tool_use_id)

        if not pending_tool_uses:
            last_valid = i + 1

    return last_valid


def truncate_to_valid_message_chain(
    records: list[SessionRecord],
) -> list[SessionRecord]:
    return records[:validate_message_chain(records)]


def records_from_last_compact_boundary(
    records: list[SessionRecord],
) -> list[SessionRecord]:
    last_boundary = -1
    for i, rec in enumerate(records):
        if rec.type == RecordType.COMPACT_BOUNDARY:
            last_boundary = i
    if last_boundary < 0:
        return records
    return records[last_boundary:]
