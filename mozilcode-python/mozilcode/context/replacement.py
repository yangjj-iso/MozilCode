"""tool-result 内容替换记录状态。

跟踪落盘替换记录，供 Layer1 预算与会话恢复。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from mozilcode.conversation import Message


@dataclass
class ContentReplacementState:
    seen_ids: set[str] = field(default_factory=set)
    replacements: dict[str, str] = field(default_factory=dict)


@dataclass
class ContentReplacementRecord:
    tool_use_id: str
    replacement: str
    kind: str = "tool-result"


REPLACEMENT_RECORDS_FILENAME = "replacement_records.jsonl"


def create_replacement_state() -> ContentReplacementState:
    return ContentReplacementState()


def clone_replacement_state(src: ContentReplacementState) -> ContentReplacementState:
    return ContentReplacementState(
        seen_ids=set(src.seen_ids),
        replacements=dict(src.replacements),
    )


def append_replacement_records(
    session_dir: Path, records: list[ContentReplacementRecord]
) -> None:
    if not records:
        return
    path = session_dir / REPLACEMENT_RECORDS_FILENAME
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(
                json.dumps(
                    {
                        "kind": record.kind,
                        "tool_use_id": record.tool_use_id,
                        "replacement": record.replacement,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def load_replacement_records(session_dir: Path) -> list[ContentReplacementRecord]:
    path = session_dir / REPLACEMENT_RECORDS_FILENAME
    if not path.exists():
        return []
    out: list[ContentReplacementRecord] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            out.append(
                ContentReplacementRecord(
                    kind=obj.get("kind", "tool-result"),
                    tool_use_id=obj["tool_use_id"],
                    replacement=obj["replacement"],
                )
            )
    return out


def reconstruct_replacement_state(
    messages: list[Message],
    records: list[ContentReplacementRecord],
    inherited_replacements: Mapping[str, str] | None = None,
) -> ContentReplacementState:
    state = create_replacement_state()
    candidate_ids: set[str] = set()
    for msg in messages:
        for tool_result in msg.tool_results:
            candidate_ids.add(tool_result.tool_use_id)
    state.seen_ids.update(candidate_ids)
    for record in records:
        if record.kind == "tool-result" and record.tool_use_id in candidate_ids:
            state.replacements[record.tool_use_id] = record.replacement
    if inherited_replacements:
        for tool_use_id, replacement in inherited_replacements.items():
            if tool_use_id in candidate_ids and tool_use_id not in state.replacements:
                state.replacements[tool_use_id] = replacement
    return state
