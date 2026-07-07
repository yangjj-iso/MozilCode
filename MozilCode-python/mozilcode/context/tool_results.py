from __future__ import annotations

import os
import shutil
from pathlib import Path

from mozilcode.context.replacement import (
    ContentReplacementRecord,
    ContentReplacementState,
)
from mozilcode.conversation import (
    ConversationManager,
    Message,
    ToolResultBlock,
)


SINGLE_RESULT_CHAR_LIMIT = 50_000
AGGREGATE_CHAR_LIMIT = 200_000
PREVIEW_CHARS = 2_000

KEEP_RECENT_TURNS = 10
OLD_RESULT_SNIP_CHARS = 2_000
SNIPPED_TAG = "<snipped>"

PERSISTED_TAG = "<persisted-output>"

SESSION_SUBDIR = ".mozilcode/session/tool-results"

__all__ = [
    "AGGREGATE_CHAR_LIMIT",
    "KEEP_RECENT_TURNS",
    "OLD_RESULT_SNIP_CHARS",
    "PERSISTED_TAG",
    "PREVIEW_CHARS",
    "SESSION_SUBDIR",
    "SINGLE_RESULT_CHAR_LIMIT",
    "SNIPPED_TAG",
    "apply_tool_result_budget",
    "cleanup_tool_results",
    "ensure_session_dir",
    "make_persisted_preview",
    "persist_tool_result",
]


def ensure_session_dir(work_dir: str) -> Path:
    session_dir = Path(work_dir) / SESSION_SUBDIR
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def cleanup_tool_results(session_dir: Path) -> None:
    if session_dir.exists():
        shutil.rmtree(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)


def persist_tool_result(tool_use_id: str, content: str, session_dir: Path) -> Path:
    file_path = session_dir / f"{tool_use_id}.txt"
    try:
        fd = os.open(str(file_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except FileExistsError:
        pass
    return file_path


def make_persisted_preview(content: str, file_path: Path) -> str:
    size_kb = len(content.encode("utf-8")) // 1024
    preview = content[:PREVIEW_CHARS]
    return (
        f"{PERSISTED_TAG}\n"
        f"输出太大（{size_kb}KB），完整内容已保存到：\n"
        f"{file_path}\n"
        f"\n"
        f"预览（前 2KB）：\n"
        f"{preview}\n"
        f"</persisted-output>"
    )


def apply_tool_result_budget(
    conversation: ConversationManager,
    session_dir: Path,
    state: ContentReplacementState,
) -> tuple[ConversationManager, list[ContentReplacementRecord]]:
    """
    Design B: 不 mutate 原 conversation。

    返回一个新的 ConversationManager，其中 tool_result.content 已根据 state.replacements
    应用了决策，并对本轮 fresh 候选执行了 Pass 1（单条超限）+ Pass 2（聚合超限）。
    Pass 3（陈旧裁剪）在新 history 上跑，仍然 stateless（边界 drift 是已知 trade-off）。

    state 会被 mutate：本轮新决定的 id 进入 seen_ids，新决定替换的 id 进入 replacements。
    """
    new_records: list[ContentReplacementRecord] = []
    new_history: list[Message] = []

    for msg in conversation.history:
        if not msg.tool_results:
            new_history.append(msg)
            continue

        decisions: dict[str, str] = {}
        fresh: list[ToolResultBlock] = []

        for tool_result in msg.tool_results:
            tool_use_id = tool_result.tool_use_id
            if tool_use_id in state.replacements:
                decisions[tool_use_id] = state.replacements[tool_use_id]
            elif tool_use_id in state.seen_ids:
                decisions[tool_use_id] = tool_result.content
            elif tool_result.content.startswith(PERSISTED_TAG):
                _record_replacement(
                    tool_use_id,
                    tool_result.content,
                    decisions,
                    state,
                    new_records,
                )
            else:
                fresh.append(tool_result)

        persisted_p1: set[str] = set()
        for tool_result in fresh:
            if len(tool_result.content) > SINGLE_RESULT_CHAR_LIMIT:
                preview = _persist_and_preview(tool_result, session_dir)
                _record_replacement(
                    tool_result.tool_use_id,
                    preview,
                    decisions,
                    state,
                    new_records,
                )
                persisted_p1.add(tool_result.tool_use_id)

        remaining = [
            tool_result
            for tool_result in fresh
            if tool_result.tool_use_id not in persisted_p1
        ]
        total = sum(len(content) for content in decisions.values()) + sum(
            len(tool_result.content) for tool_result in remaining
        )
        if total > AGGREGATE_CHAR_LIMIT:
            ranked = sorted(
                remaining,
                key=lambda tool_result: len(tool_result.content),
                reverse=True,
            )
            for tool_result in ranked:
                if total <= AGGREGATE_CHAR_LIMIT:
                    break
                preview = _persist_and_preview(tool_result, session_dir)
                old_len = len(tool_result.content)
                _record_replacement(
                    tool_result.tool_use_id,
                    preview,
                    decisions,
                    state,
                    new_records,
                )
                total -= old_len - len(preview)

        for tool_result in fresh:
            if tool_result.tool_use_id not in state.replacements:
                state.seen_ids.add(tool_result.tool_use_id)
                decisions[tool_result.tool_use_id] = tool_result.content

        new_history.append(_copy_message_with_results(msg, decisions))

    new_history = _snip_stale_messages(new_history)

    new_conv = ConversationManager()
    new_conv.history = new_history
    new_conv.env_injected = conversation.env_injected
    new_conv.ltm_injected = conversation.ltm_injected
    new_conv.last_input_tokens = conversation.last_input_tokens
    new_conv.baseline_tokens = conversation.baseline_tokens
    new_conv.anchor_count = conversation.anchor_count

    return new_conv, new_records


def _record_replacement(
    tool_use_id: str,
    replacement: str,
    decisions: dict[str, str],
    state: ContentReplacementState,
    records: list[ContentReplacementRecord],
) -> None:
    decisions[tool_use_id] = replacement
    state.replacements[tool_use_id] = replacement
    state.seen_ids.add(tool_use_id)
    records.append(
        ContentReplacementRecord(
            tool_use_id=tool_use_id,
            replacement=replacement,
        )
    )


def _persist_and_preview(tool_result: ToolResultBlock, session_dir: Path) -> str:
    file_path = persist_tool_result(
        tool_result.tool_use_id,
        tool_result.content,
        session_dir,
    )
    return make_persisted_preview(tool_result.content, file_path)


def _count_turns(messages: list[Message]) -> int:
    count = 0
    for message in messages:
        if message.role == "assistant" and not message.tool_uses:
            count += 1
    return count


def _copy_message_with_results(
    msg: Message,
    decisions: dict[str, str],
) -> Message:
    return Message(
        role=msg.role,
        content=msg.content,
        tool_uses=list(msg.tool_uses),
        tool_results=[
            ToolResultBlock(
                tool_use_id=tool_result.tool_use_id,
                content=decisions[tool_result.tool_use_id],
                is_error=tool_result.is_error,
            )
            for tool_result in msg.tool_results
        ],
        thinking_blocks=list(msg.thinking_blocks),
    )


def _copy_message_with_tool_results(
    msg: Message,
    new_tool_results: list[ToolResultBlock],
) -> Message:
    return Message(
        role=msg.role,
        content=msg.content,
        tool_uses=list(msg.tool_uses),
        tool_results=new_tool_results,
        thinking_blocks=list(msg.thinking_blocks),
    )


def _snip_stale_messages(
    history: list[Message],
) -> list[Message]:
    total_turns = _count_turns(history)
    if total_turns <= KEEP_RECENT_TURNS:
        return history

    out: list[Message] = []
    turns_seen = 0
    old_boundary = total_turns - KEEP_RECENT_TURNS

    for msg in history:
        if msg.role == "assistant" and not msg.tool_uses:
            turns_seen += 1
        if turns_seen > old_boundary or not msg.tool_results:
            out.append(msg)
            continue

        new_results: list[ToolResultBlock] = []
        changed = False
        for tool_result in msg.tool_results:
            if (
                tool_result.content.startswith(SNIPPED_TAG)
                or tool_result.content.startswith(PERSISTED_TAG)
                or len(tool_result.content) <= OLD_RESULT_SNIP_CHARS
            ):
                new_results.append(tool_result)
                continue
            preview = tool_result.content[:200]
            orig_len = len(tool_result.content)
            new_content = (
                f"{SNIPPED_TAG}\n"
                f"(旧结果已裁剪，原始长度 {orig_len} 字符)\n"
                f"{preview}\n"
                f"… (snipped)"
            )
            new_results.append(
                ToolResultBlock(
                    tool_use_id=tool_result.tool_use_id,
                    content=new_content,
                    is_error=tool_result.is_error,
                )
            )
            changed = True

        out.append(_copy_message_with_tool_results(msg, new_results) if changed else msg)

    return out
