from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mozilcode.config import ConfigError, MemoryConfig, MemoryProviderConfig, load_config
from mozilcode.conversation import (
    ConversationManager,
    Message,
    ToolResultBlock,
    ToolUseBlock,
)
from mozilcode.memory.auto_memory import MemoryManager
from mozilcode.memory.instructions import (
    MAX_INCLUDE_DEPTH,
    load_instructions,
    process_includes,
)
from mozilcode.memory.session import (
    RecordType,
    ResumeResult,
    Session,
    SessionManager,
    SessionMeta,
    SessionRecord,

    make_compact_boundary,
    parse_compact_boundary,
    records_to_messages,
    validate_message_chain,
)
from mozilcode.memory.providers import (
    BaseMemoryProvider,
    MemoryEvent,
    MemoryHub,
    MemoryItem,
    MemoryProviderLoadError,
    MemoryScope,
    build_memory_hub,
)
from mozilcode.validator import validate_memory

# =========================================================================
# A. 指令文件（MOZILCODE.md）
# =========================================================================

class TestProcessIncludes:
    def test_no_includes(self, tmp_path: Path) -> None:
        content = "line1\nline2\nline3"
        result = process_includes(content, tmp_path, tmp_path)
        assert result == content

    def test_basic_include(self, tmp_path: Path) -> None:
        child = tmp_path / "child.md"
        child.write_text("included content", encoding="utf-8")
        content = "before\n@include ./child.md\nafter"
        result = process_includes(content, tmp_path, tmp_path)
        assert "included content" in result
        assert "before" in result
        assert "after" in result

    def test_recursive_include(self, tmp_path: Path) -> None:
        grandchild = tmp_path / "grandchild.md"
        grandchild.write_text("deep content", encoding="utf-8")
        child = tmp_path / "child.md"
        child.write_text("@include ./grandchild.md", encoding="utf-8")
        content = "@include ./child.md"
        result = process_includes(content, tmp_path, tmp_path)
        assert "deep content" in result

    def test_depth_limit(self, tmp_path: Path) -> None:
        content = "should stop"
        result = process_includes(content, tmp_path, tmp_path, depth=MAX_INCLUDE_DEPTH)
        assert result == content

    def test_path_outside_project_blocked(self, tmp_path: Path) -> None:
        content = "@include ../../etc/passwd"
        result = process_includes(content, tmp_path, tmp_path)
        assert "blocked: path outside project" in result

    def test_file_not_found(self, tmp_path: Path) -> None:
        content = "@include ./nonexistent.md"
        result = process_includes(content, tmp_path, tmp_path)
        assert "skipped: file not found" in result

class TestLoadInstructions:
    def test_single_layer(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mozilcode_md = tmp_path / "MOZILCODE.md"
        mozilcode_md.write_text("project instructions", encoding="utf-8")
        result = load_instructions(str(tmp_path))
        assert "project instructions" in result

    def test_multi_layer_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root_md = tmp_path / "MOZILCODE.md"
        root_md.write_text("root level", encoding="utf-8")
        dotdir = tmp_path / ".mozilcode"
        dotdir.mkdir()
        dot_md = dotdir / "MOZILCODE.md"
        dot_md.write_text("dotdir level", encoding="utf-8")
        result = load_instructions(str(tmp_path))
        assert result.index("root level") < result.index("dotdir level")
        assert "\n---\n" in result

    def test_no_files_returns_empty(self, tmp_path: Path) -> None:
        result = load_instructions(str(tmp_path))
        assert result == ""

# =========================================================================
# B. 会话记录 SessionRecord
# =========================================================================

class TestSessionRecord:
    def test_user_message_roundtrip(self) -> None:
        msg = Message(role="user", content="hello world")
        records = SessionRecord.from_message(msg)
        assert len(records) == 1
        assert records[0].type == RecordType.USER
        assert records[0].content == "hello world"

        line = records[0].to_jsonl()
        restored = SessionRecord.from_jsonl(line)
        assert restored is not None
        assert restored.type == RecordType.USER
        assert restored.content == "hello world"

    def test_assistant_with_tool_uses(self) -> None:
        msg = Message(
            role="assistant",
            content="Let me check",
            tool_uses=[
                ToolUseBlock(tool_use_id="t1", tool_name="ReadFile", arguments={"path": "/a"})
            ],
        )
        records = SessionRecord.from_message(msg)
        assert len(records) == 1
        assert records[0].type == RecordType.ASSISTANT
        assert isinstance(records[0].content, list)
        assert records[0].content[0]["type"] == "text"
        assert records[0].content[1]["type"] == "tool_use"

    def test_tool_results_multiple_records(self) -> None:
        msg = Message(
            role="user",
            content="",
            tool_results=[
                ToolResultBlock(tool_use_id="t1", content="result1"),
                ToolResultBlock(tool_use_id="t2", content="result2", is_error=True),
            ],
        )
        records = SessionRecord.from_message(msg)
        assert len(records) == 2
        assert records[0].type == RecordType.TOOL_RESULT
        assert records[0].tool_use_id == "t1"
        assert records[1].is_error is True

    def test_malformed_jsonl_returns_none(self) -> None:
        assert SessionRecord.from_jsonl("{bad json") is None
        assert SessionRecord.from_jsonl('{"type":"unknown","content":"x","timestamp":"2025-01-01T00:00:00"}') is None

    def test_plain_assistant_message(self) -> None:
        msg = Message(role="assistant", content="done")
        records = SessionRecord.from_message(msg)
        assert len(records) == 1
        assert records[0].content == "done"

# =========================================================================
# C. 会话 Session 与会话管理器 SessionManager
# =========================================================================

class TestSession:
    def test_append_writes_jsonl_and_updates_meta(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".mozilcode" / "sessions"
        sessions_dir.mkdir(parents=True)
        meta = SessionMeta(id="test_session")
        meta.save(sessions_dir / "test_session.meta")
        jsonl_path = sessions_dir / "test_session.jsonl"

        with open(jsonl_path, "a", encoding="utf-8") as f:
            session = Session("test_session", f, meta, sessions_dir)
            session.append(Message(role="user", content="hello"))
            session.append(Message(role="assistant", content="hi"))

        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert meta.message_count == 2
        assert meta.title == "hello"

    def test_title_set_from_first_user_message(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".mozilcode" / "sessions"
        sessions_dir.mkdir(parents=True)
        meta = SessionMeta(id="test_session")
        jsonl_path = sessions_dir / "test_session.jsonl"

        with open(jsonl_path, "a", encoding="utf-8") as f:
            session = Session("test_session", f, meta, sessions_dir)
            session.append(Message(role="assistant", content="welcome"))
            assert meta.title == ""
            session.append(Message(role="user", content="my first question"))
            assert meta.title == "my first question"

class TestSessionManager:

    def test_create_and_list(self, tmp_path: Path) -> None:
        mgr = SessionManager(str(tmp_path))
        s1 = mgr.create()
        s1.append(Message(role="user", content="test"))
        s1.close()

        s2 = mgr.create()
        s2.append(Message(role="user", content="test2"))
        s2.close()

        metas = mgr.list()
        assert len(metas) == 2
        assert metas[0].last_active >= metas[1].last_active

    def test_delete(self, tmp_path: Path) -> None:
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        sid = s.session_id
        s.close()

        assert mgr.delete(sid) is True
        assert mgr.delete(sid) is False
        assert len(mgr.list()) == 0

    def test_cleanup_removes_old_sessions(self, tmp_path: Path) -> None:
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        s.meta.last_active = datetime.now(timezone.utc) - timedelta(days=31)
        s.meta.save(mgr._sessions_dir / f"{s.session_id}.meta")
        s.close()

        removed = mgr.cleanup(max_age_days=30)
        assert removed == 1
        assert len(mgr.list()) == 0

    def test_create_generates_valid_id(self, tmp_path: Path) -> None:
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        assert s.session_id.startswith("session_")
        assert len(s.session_id.split("_")) == 4
        s.close()

# =========================================================================
# D. 消息链校验与会话恢复
# =========================================================================

class TestValidateMessageChain:
    def test_complete_chain(self) -> None:
        now = datetime.now(timezone.utc)
        records = [
            SessionRecord(type=RecordType.USER, content="hi", timestamp=now),
            SessionRecord(
                type=RecordType.ASSISTANT,
                content=[
                    {"type": "text", "text": "checking"},
                    {"type": "tool_use", "id": "t1", "name": "ReadFile", "input": {}},
                ],
                timestamp=now,
            ),
            SessionRecord(
                type=RecordType.TOOL_RESULT,
                content="file content",
                timestamp=now,
                tool_use_id="t1",
            ),
            SessionRecord(type=RecordType.ASSISTANT, content="done", timestamp=now),
        ]
        assert validate_message_chain(records) == 4

    def test_truncate_at_missing_tool_result(self) -> None:
        now = datetime.now(timezone.utc)
        records = [
            SessionRecord(type=RecordType.USER, content="hi", timestamp=now),
            SessionRecord(type=RecordType.ASSISTANT, content="ok", timestamp=now),
            SessionRecord(
                type=RecordType.ASSISTANT,
                content=[
                    {"type": "tool_use", "id": "t2", "name": "Bash", "input": {}},
                ],
                timestamp=now,
            ),
        ]
        assert validate_message_chain(records) == 2

    def test_empty_records(self) -> None:
        assert validate_message_chain([]) == 0

class TestRecordsToMessages:
    def test_basic_roundtrip(self) -> None:
        now = datetime.now(timezone.utc)
        records = [
            SessionRecord(type=RecordType.USER, content="hello", timestamp=now),
            SessionRecord(type=RecordType.ASSISTANT, content="world", timestamp=now),
        ]
        messages = records_to_messages(records)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    def test_tool_result_grouping(self) -> None:
        now = datetime.now(timezone.utc)
        records = [
            SessionRecord(type=RecordType.USER, content="go", timestamp=now),
            SessionRecord(
                type=RecordType.ASSISTANT,
                content=[
                    {"type": "tool_use", "id": "t1", "name": "ReadFile", "input": {}},
                    {"type": "tool_use", "id": "t2", "name": "Bash", "input": {}},
                ],
                timestamp=now,
            ),
            SessionRecord(
                type=RecordType.TOOL_RESULT, content="r1", timestamp=now, tool_use_id="t1"
            ),
            SessionRecord(
                type=RecordType.TOOL_RESULT, content="r2", timestamp=now, tool_use_id="t2"
            ),
            SessionRecord(type=RecordType.ASSISTANT, content="done", timestamp=now),
        ]
        messages = records_to_messages(records)
        assert len(messages) == 4
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"
        assert len(messages[1].tool_uses) == 2
        assert messages[2].role == "user"
        assert len(messages[2].tool_results) == 2
        assert messages[3].role == "assistant"

    def test_system_prompt_skipped(self) -> None:
        now = datetime.now(timezone.utc)
        records = [
            SessionRecord(type=RecordType.SYSTEM_PROMPT, content="system", timestamp=now),
            SessionRecord(type=RecordType.USER, content="hi", timestamp=now),
        ]
        messages = records_to_messages(records)
        assert len(messages) == 1
        assert messages[0].content == "hi"

class TestSessionResume:
    def test_resume_restores_messages(self, tmp_path: Path) -> None:
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        sid = s.session_id
        s.append(Message(role="user", content="hello"))
        s.append(Message(role="assistant", content="hi"))
        s.close()

        result = mgr.resume(sid)
        assert result is not None
        assert len(result.messages) == 2
        assert result.messages[0].content == "hello"
        assert result.messages[1].content == "hi"
        result.session.close()

    def test_resume_nonexistent_returns_none(self, tmp_path: Path) -> None:
        mgr = SessionManager(str(tmp_path))
        assert mgr.resume("nonexistent") is None

    def test_resume_truncates_incomplete_chain(self, tmp_path: Path) -> None:
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        sid = s.session_id
        s.append(Message(role="user", content="start"))
        s.append(Message(role="assistant", content="ok"))
        s.append(
            Message(
                role="assistant",
                content="checking",
                tool_uses=[
                    ToolUseBlock(tool_use_id="t1", tool_name="Bash", arguments={"command": "ls"})
                ],
            )
        )
        s.close()

        result = mgr.resume(sid)
        assert result is not None
        assert len(result.messages) == 2
        result.session.close()

# =========================================================================
# D2. 压缩边界的持久化 + 恢复时重新加载压缩后的状态
# =========================================================================

class TestCompactBoundaryRoundTrip:
    def test_make_and_parse_boundary_text_only(self) -> None:
        keep = [
            Message(role="user", content="recent question"),
            Message(role="assistant", content="recent answer"),
        ]
        rec = make_compact_boundary("the summary", keep)
        assert rec.type == RecordType.COMPACT_BOUNDARY
        assert rec.content["summary"] == "the summary"

        # JSONL 往返序列化（content 是一个 dict，必须能完整地序列化/反序列化）
        line = rec.to_jsonl()
        restored = SessionRecord.from_jsonl(line)
        assert restored is not None
        assert restored.type == RecordType.COMPACT_BOUNDARY

        summary, keep_msgs = parse_compact_boundary(restored)
        assert summary == "the summary"
        assert len(keep_msgs) == 2
        assert keep_msgs[0].role == "user"
        assert keep_msgs[0].content == "recent question"
        assert keep_msgs[1].role == "assistant"
        assert keep_msgs[1].content == "recent answer"

    def test_boundary_preserves_tool_pairs_in_keep(self) -> None:
        # 保留的尾部消息中包含 tool_use ↔ tool_result 配对，必须完整保留
        keep = [
            Message(
                role="assistant",
                content="running",
                tool_uses=[
                    ToolUseBlock(tool_use_id="t9", tool_name="Bash", arguments={"command": "ls"})
                ],
            ),
            Message(
                role="user",
                content="",
                tool_results=[ToolResultBlock(tool_use_id="t9", content="file.txt")],
            ),
            Message(role="assistant", content="done"),
        ]
        rec = make_compact_boundary("sum", keep)
        restored = SessionRecord.from_jsonl(rec.to_jsonl())
        _, keep_msgs = parse_compact_boundary(restored)
        assert len(keep_msgs) == 3
        assert keep_msgs[0].tool_uses[0].tool_use_id == "t9"
        assert keep_msgs[1].tool_results[0].tool_use_id == "t9"
        assert keep_msgs[1].tool_results[0].content == "file.txt"
        assert keep_msgs[2].content == "done"

    def test_parse_malformed_boundary_degrades(self) -> None:
        bad = SessionRecord(
            type=RecordType.COMPACT_BOUNDARY, content="not a dict",
            timestamp=datetime.now(timezone.utc),
        )
        summary, keep_msgs = parse_compact_boundary(bad)
        assert summary == ""
        assert keep_msgs == []

    def test_resume_rebuilds_compacted_state(self, tmp_path: Path) -> None:
        """核心往返流程：原始前缀 + 边界（摘要 + 保留消息）+ 边界之后的消息。

        恢复时必须重建出「已压缩」的状态：摘要存在、保留的消息原样保留、
        边界之前的原始前缀不被重放，且边界之后追加的消息正常存在。
        """
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        sid = s.session_id

        # 已被摘要掉的原始前缀——不应被重放。
        s.append(Message(role="user", content="OLD raw question one"))
        s.append(Message(role="assistant", content="OLD raw answer one"))
        s.append(Message(role="user", content="OLD raw question two"))
        s.append(Message(role="assistant", content="OLD raw answer two"))

        # 边界内联了摘要 + 原样保留的尾部消息。
        keep = [
            Message(role="user", content="KEPT recent question"),
            Message(role="assistant", content="KEPT recent answer"),
        ]
        s.append_record(make_compact_boundary("SUMMARY OF OLD STUFF", keep))

        # 边界之后的续写。
        s.append(Message(role="user", content="NEW followup"))
        s.append(Message(role="assistant", content="NEW reply"))
        s.close()

        result = mgr.resume(sid)
        assert result is not None
        contents = [m.content for m in result.messages]

        # 摘要存在（以一条 user 消息的形式呈现）
        assert any("SUMMARY OF OLD STUFF" in c for c in contents)
        # 保留的尾部消息原样存在
        assert "KEPT recent question" in contents
        assert "KEPT recent answer" in contents
        # 边界之后的续写存在
        assert "NEW followup" in contents
        assert "NEW reply" in contents
        # 边界之前的原始前缀未被重放
        assert all("OLD raw" not in c for c in contents)

        # 结构顺序：先摘要，再保留消息，最后是边界之后的消息。
        summary_idx = next(i for i, c in enumerate(contents) if "SUMMARY OF OLD STUFF" in c)
        keep_idx = contents.index("KEPT recent question")
        post_idx = contents.index("NEW followup")
        assert summary_idx < keep_idx < post_idx
        result.session.close()

    def test_resume_uses_last_boundary_when_multiple(self, tmp_path: Path) -> None:
        """链式压缩：只有最后一个边界才决定恢复后的状态。"""
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        sid = s.session_id

        s.append(Message(role="user", content="gen0 raw"))
        s.append_record(make_compact_boundary("FIRST summary", [
            Message(role="user", content="gen1 kept"),
        ]))
        s.append(Message(role="assistant", content="between boundaries"))
        s.append_record(make_compact_boundary("SECOND summary", [
            Message(role="user", content="gen2 kept"),
        ]))
        s.append(Message(role="user", content="after second"))
        s.close()

        result = mgr.resume(sid)
        assert result is not None
        contents = [m.content for m in result.messages]
        assert any("SECOND summary" in c for c in contents)
        assert "gen2 kept" in contents
        assert "after second" in contents
        # 第一代压缩的所有内容都已消失。
        assert all("FIRST summary" not in c for c in contents)
        assert "gen1 kept" not in contents
        assert "between boundaries" not in contents
        assert all("gen0 raw" not in c for c in contents)
        result.session.close()

    def test_resume_no_boundary_full_replay(self, tmp_path: Path) -> None:
        """向后兼容：没有边界的会话仍然完整重放。"""
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        sid = s.session_id
        s.append(Message(role="user", content="q1"))
        s.append(Message(role="assistant", content="a1"))
        s.append(Message(role="user", content="q2"))
        s.append(Message(role="assistant", content="a2"))
        s.close()

        result = mgr.resume(sid)
        assert result is not None
        contents = [m.content for m in result.messages]
        assert contents == ["q1", "a1", "q2", "a2"]
        result.session.close()

    def test_append_record_does_not_bump_message_count(self, tmp_path: Path) -> None:
        mgr = SessionManager(str(tmp_path))
        s = mgr.create()
        s.append(Message(role="user", content="hi"))
        before = s.meta.message_count
        s.append_record(make_compact_boundary("x", []))
        assert s.meta.message_count == before  # 边界只是一个标记，不算一轮对话
        s.close()


# =========================================================================
# F. 会话元数据 SessionMeta
# =========================================================================

class TestSessionMeta:
    def test_save_and_load(self, tmp_path: Path) -> None:
        meta = SessionMeta(
            id="test_123",
            title="Test session",
            summary="A test",
            message_count=10,
            total_tokens=5000,
        )
        path = tmp_path / "test.meta"
        meta.save(path)

        loaded = SessionMeta.load(path)
        assert loaded is not None
        assert loaded.id == "test_123"
        assert loaded.title == "Test session"
        assert loaded.message_count == 10

    def test_load_invalid_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.meta"
        path.write_text("not json", encoding="utf-8")
        assert SessionMeta.load(path) is None

# =========================================================================
# G. 记忆管理器 MemoryManager
# =========================================================================

class TestMemoryManager:
    def test_load_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        mgr = MemoryManager(str(tmp_path / "project"))
        assert mgr.load() == ""

    def test_load_merges_user_and_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        user_mem = fake_home / ".mozilcode" / "memories.md"
        user_mem.parent.mkdir(parents=True)
        user_mem.write_text("### 用户偏好\n- prefer spaces", encoding="utf-8")

        project_mem = tmp_path / "project" / ".mozilcode" / "memories.md"
        project_mem.parent.mkdir(parents=True)
        project_mem.write_text("### 项目知识\n- uses PostgreSQL", encoding="utf-8")

        mgr = MemoryManager(str(tmp_path / "project"))
        result = mgr.load()
        assert "prefer spaces" in result
        assert "uses PostgreSQL" in result

    def test_clear(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        user_mem = fake_home / ".mozilcode" / "memories.md"
        user_mem.parent.mkdir(parents=True)
        user_mem.write_text("### 用户偏好\n- something", encoding="utf-8")

        project_mem = tmp_path / "project" / ".mozilcode" / "memories.md"
        project_mem.parent.mkdir(parents=True)
        project_mem.write_text("### 项目知识\n- something", encoding="utf-8")

        mgr = MemoryManager(str(tmp_path / "project"))
        mgr.clear()
        assert mgr.load() == ""

    def test_get_display_text_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        mgr = MemoryManager(str(tmp_path / "project"))
        assert "没有任何自动记忆" in mgr.get_display_text()

    def test_write_memories_splits_correctly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        mgr = MemoryManager(str(tmp_path / "project"))
        mgr._write_memories(
            "### 用户偏好\n- use spaces\n\n"
            "### 纠正反馈\n- use mutex not channel\n\n"
            "### 项目知识\n- uses PostgreSQL\n\n"
            "### 参考资料\n- docs at example.com\n"
        )

        user_content = mgr._user_path.read_text(encoding="utf-8")
        assert "use spaces" in user_content
        assert "use mutex" in user_content
        assert "PostgreSQL" not in user_content

        project_content = mgr._project_path.read_text(encoding="utf-8")
        assert "uses PostgreSQL" in project_content
        assert "docs at example.com" in project_content
        assert "use spaces" not in project_content

# =========================================================================
# H. 会话注入长期记忆 inject_long_term_memory
# =========================================================================

class TestConversationInjection:
    def test_inject_long_term_memory(self) -> None:
        conv = ConversationManager()
        conv.inject_environment("env info")
        conv.inject_long_term_memory("project rules", "user prefs")

        assert len(conv.history) == 2
        assert conv.history[0].content == "env info"
        assert "<system-reminder>" in conv.history[1].content
        assert "mozilcodeMd" in conv.history[1].content
        assert "project rules" in conv.history[1].content
        assert "autoMemory" in conv.history[1].content
        assert "user prefs" in conv.history[1].content
        assert "currentDate" in conv.history[1].content
        assert conv.ltm_injected is True

    def test_inject_idempotent(self) -> None:
        conv = ConversationManager()
        conv.inject_long_term_memory("rules", "mems")
        conv.inject_long_term_memory("rules2", "mems2")
        assert sum(1 for m in conv.history if "<system-reminder>" in m.content) == 1

    def test_inject_instructions_only(self) -> None:
        conv = ConversationManager()
        conv.inject_long_term_memory("rules", "")
        assert len(conv.history) == 1
        assert "<system-reminder>" in conv.history[0].content
        assert "mozilcodeMd" in conv.history[0].content
        assert "rules" in conv.history[0].content

    def test_inject_memories_only(self) -> None:
        conv = ConversationManager()
        conv.inject_long_term_memory("", "mems")
        assert len(conv.history) == 1
        assert "<system-reminder>" in conv.history[0].content
        assert "autoMemory" in conv.history[0].content
        assert "mems" in conv.history[0].content

    def test_inject_nothing(self) -> None:
        conv = ConversationManager()
        conv.inject_long_term_memory("", "")
        assert len(conv.history) == 0
        assert conv.ltm_injected is False

    def test_replace_history_resets_ltm(self) -> None:
        conv = ConversationManager()
        conv.inject_long_term_memory("rules", "mems")
        assert conv.ltm_injected is True
        conv.replace_history([])
        assert conv.ltm_injected is False

# =========================================================================
# I. 记忆抽取 prompt 的构造
# =========================================================================

class TestMemoryExtraction:
    def test_extraction_prompt_contains_categories(self, tmp_path: Path) -> None:
        from mozilcode.memory.auto_memory import MEMORY_EXTRACTION_PROMPT

        assert "用户偏好" in MEMORY_EXTRACTION_PROMPT
        assert "纠正反馈" in MEMORY_EXTRACTION_PROMPT
        assert "项目知识" in MEMORY_EXTRACTION_PROMPT
        assert "参考资料" in MEMORY_EXTRACTION_PROMPT
        assert "不要重复添加" in MEMORY_EXTRACTION_PROMPT


# =========================================================================
# J. 记忆插件 MemoryHub / Provider
# =========================================================================

class _StaticMemoryProvider(BaseMemoryProvider):
    name = "static"
    kind = "test.static"
    version = "1.0"

    def __init__(self) -> None:
        self.initialized = False
        self.events: list[str] = []
        self.writes: list[str] = []

    async def initialize(self) -> None:
        self.initialized = True

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        return f"query={query}; project={scope.project_root}"

    async def observe(self, event: MemoryEvent) -> None:
        self.events.append(event.type)

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        return [MemoryItem(content=f"{query}-{i}") for i in range(limit)]

    async def write(self, item: MemoryItem) -> None:
        self.writes.append(item.content)


class _FailingMemoryProvider(BaseMemoryProvider):
    name = "failing"
    kind = "test.failing"
    version = "1.0"

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        raise RuntimeError("boom")


class TestMemoryProviders:
    @pytest.mark.asyncio
    async def test_memory_hub_loads_observes_searches_and_writes(self, tmp_path: Path) -> None:
        provider = _StaticMemoryProvider()
        hub = MemoryHub(providers=[provider])

        scope = MemoryScope(query="hello", project_root=str(tmp_path))
        context = await hub.load_context("hello", scope)
        await hub.observe(MemoryEvent(type="turn_committed"))
        items = await hub.search("needle", limit=2)
        await hub.write(MemoryItem(content="remember this"))

        assert provider.initialized is True
        assert "## static" in context
        assert "query=hello" in context
        assert provider.events == ["turn_committed"]
        assert [item.content for item in items] == ["needle-0", "needle-1"]
        assert provider.writes == ["remember this"]

    @pytest.mark.asyncio
    async def test_memory_hub_isolates_provider_failures(self, tmp_path: Path) -> None:
        hub = MemoryHub(
            providers=[_FailingMemoryProvider(), _StaticMemoryProvider()],
            load_timeout=0.1,
        )

        context = await hub.load_context("hello", MemoryScope(project_root=str(tmp_path)))
        status = hub.status()

        assert "## static" in context
        failing = next(p for p in status["providers"] if p["name"] == "failing")
        assert "RuntimeError" in failing["last_error"]

    @pytest.mark.asyncio
    async def test_default_memory_hub_wraps_markdown_memory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        project = tmp_path / "project"
        user_mem = fake_home / ".mozilcode" / "memories.md"
        project_mem = project / ".mozilcode" / "memories.md"
        user_mem.parent.mkdir(parents=True)
        project_mem.parent.mkdir(parents=True)
        user_mem.write_text("### 用户偏好\n- prefer tests", encoding="utf-8")
        project_mem.write_text("### 项目知识\n- has plugin memory", encoding="utf-8")

        hub = build_memory_hub(None, str(project))
        assert hub is not None

        context = await hub.load_context("", MemoryScope(project_root=str(project)))

        assert "## markdown" in context
        assert "prefer tests" in context
        assert "has plugin memory" in context

    def test_disabled_memory_builds_no_hub(self, tmp_path: Path) -> None:
        hub = build_memory_hub(MemoryConfig(enabled=False), str(tmp_path))
        assert hub is None

    @pytest.mark.asyncio
    async def test_python_provider_can_be_loaded_from_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module_name = "custom_memory_provider_for_test"
        (tmp_path / f"{module_name}.py").write_text(
            "from mozilcode.memory.providers import BaseMemoryProvider\n"
            "class CustomProvider(BaseMemoryProvider):\n"
            "    kind = 'python.custom'\n"
            "    version = '0.1'\n"
            "    def __init__(self, project_root, config):\n"
            "        self.name = config['name']\n"
            "        self.project_root = project_root\n"
            "    async def load_context(self, query, scope):\n"
            "        return f'{self.name}:{self.project_root}:{query}'\n",
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        cfg = MemoryConfig(
            providers=[
                MemoryProviderConfig(
                    name="custom",
                    type="python",
                    module=module_name,
                    class_name="CustomProvider",
                    config={"name": "loaded"},
                )
            ]
        )

        hub = build_memory_hub(cfg, str(tmp_path))
        assert hub is not None

        context = await hub.load_context("q", MemoryScope(project_root=str(tmp_path)))

        assert "## loaded" in context
        assert "loaded:" in context

    def test_unknown_builtin_remote_provider_is_rejected(self, tmp_path: Path) -> None:
        cfg = MemoryConfig(
            providers=[
                MemoryProviderConfig(
                    name="remote",
                    type="builtin.remote",
                )
            ]
        )

        with pytest.raises(Exception, match="Unsupported memory provider type"):
            build_memory_hub(cfg, str(tmp_path))

    @pytest.mark.asyncio
    async def test_python_provider_can_use_config_only_constructor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module_name = "config_only_memory_provider_for_test"
        (tmp_path / f"{module_name}.py").write_text(
            "from mozilcode.memory.providers import BaseMemoryProvider\n"
            "class ConfigOnlyProvider(BaseMemoryProvider):\n"
            "    def __init__(self, config):\n"
            "        self.name = config['name']\n"
            "    async def load_context(self, query, scope):\n"
            "        return self.name\n",
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        cfg = MemoryConfig(
            providers=[
                MemoryProviderConfig(
                    name="config-only",
                    type="python",
                    module=module_name,
                    class_name="ConfigOnlyProvider",
                    config={"name": "loaded-config-only"},
                )
            ]
        )

        hub = build_memory_hub(cfg, str(tmp_path))
        assert hub is not None

        context = await hub.load_context("", MemoryScope(project_root=str(tmp_path)))

        assert "loaded-config-only" in context

    def test_python_provider_constructor_type_error_is_not_masked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module_name = "broken_memory_provider_for_test"
        (tmp_path / f"{module_name}.py").write_text(
            "from mozilcode.memory.providers import BaseMemoryProvider\n"
            "class BrokenProvider(BaseMemoryProvider):\n"
            "    def __init__(self, project_root, config):\n"
            "        raise TypeError('internal constructor bug')\n",
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        cfg = MemoryConfig(
            providers=[
                MemoryProviderConfig(
                    name="broken",
                    type="python",
                    module=module_name,
                    class_name="BrokenProvider",
                )
            ]
        )

        with pytest.raises(MemoryProviderLoadError, match="internal constructor bug"):
            build_memory_hub(cfg, str(tmp_path))

    def test_python_provider_missing_class_reports_loader_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module_name = "missing_class_memory_provider_for_test"
        (tmp_path / f"{module_name}.py").write_text("", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        cfg = MemoryConfig(
            providers=[
                MemoryProviderConfig(
                    name="missing",
                    type="python",
                    module=module_name,
                    class_name="MissingProvider",
                )
            ]
        )

        with pytest.raises(
            MemoryProviderLoadError,
            match="class 'MissingProvider' not found",
        ):
            build_memory_hub(cfg, str(tmp_path))

    def test_python_provider_required_positional_only_param_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module_name = "positional_only_memory_provider_for_test"
        (tmp_path / f"{module_name}.py").write_text(
            "from mozilcode.memory.providers import BaseMemoryProvider\n"
            "class PositionalOnlyProvider(BaseMemoryProvider):\n"
            "    def __init__(self, project_root, /):\n"
            "        self.project_root = project_root\n",
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        cfg = MemoryConfig(
            providers=[
                MemoryProviderConfig(
                    name="pos-only",
                    type="python",
                    module=module_name,
                    class_name="PositionalOnlyProvider",
                )
            ]
        )

        with pytest.raises(
            MemoryProviderLoadError,
            match="required parameter\\(s\\) cannot be injected by name: project_root",
        ):
            build_memory_hub(cfg, str(tmp_path))

    def test_duplicate_memory_provider_names_are_rejected(self, tmp_path: Path) -> None:
        cfg = MemoryConfig(
            providers=[
                MemoryProviderConfig(name="dup", type="builtin.markdown"),
                MemoryProviderConfig(name="dup", type="builtin.markdown"),
            ]
        )

        with pytest.raises(Exception, match="Duplicate memory provider name"):
            build_memory_hub(cfg, str(tmp_path))

    def test_programmatic_memory_provider_names_are_trimmed_without_mutation(
        self, tmp_path: Path
    ) -> None:
        provider = MemoryProviderConfig(name=" markdown ", type="builtin.markdown")

        hub = build_memory_hub(MemoryConfig(providers=[provider]), str(tmp_path))

        assert hub is not None
        assert hub.status()["providers"][0]["name"] == "markdown"
        assert provider.name == " markdown "

    def test_validate_memory_defaults_and_python_provider(self) -> None:
        defaults = validate_memory(None)
        assert defaults["enabled"] is True
        assert defaults["providers"][0]["type"] == "builtin.markdown"

        cleaned = validate_memory({
            "enabled": True,
            "providers": [
                {
                    "name": "vector",
                    "type": "python",
                    "module": " my_memory.provider ",
                    "class_name": " VectorMemory ",
                    "config": {"top_k": 8},
                }
            ],
        })

        assert cleaned["providers"][0]["module"] == "my_memory.provider"
        assert cleaned["providers"][0]["class"] == "VectorMemory"
        assert cleaned["providers"][0]["config"] == {"top_k": 8}

    def test_validate_memory_rejects_bad_config_shape(self) -> None:
        with pytest.raises(ConfigError):
            validate_memory({"providers": [{"name": "bad", "type": "python", "config": []}]})

    @pytest.mark.parametrize(
        "provider, message",
        [
            (
                {"name": "bad", "type": 123},
                "type must be a string",
            ),
            (
                {
                    "name": "bad",
                    "type": "python",
                    "module": ["my_memory.provider"],
                    "class": "Provider",
                },
                "module must be a string",
            ),
            (
                {
                    "name": "bad",
                    "type": "python",
                    "module": "my_memory.provider",
                    "class": ["Provider"],
                },
                "class must be a string",
            ),
            (
                {
                    "name": "bad",
                    "type": "python",
                    "module": "my_memory.provider",
                    "class_name": ["Provider"],
                },
                "class_name must be a string",
            ),
        ],
    )
    def test_validate_memory_rejects_bad_string_fields(
        self, provider: dict, message: str
    ) -> None:
        with pytest.raises(ConfigError, match=message):
            validate_memory({"providers": [provider]})

    @pytest.mark.parametrize(
        "provider",
        [
            {"name": "bad", "type": "python", "class": "Provider"},
            {"name": "bad", "type": "python", "module": "my_memory.provider"},
            {
                "name": "bad",
                "type": "python",
                "module": " ",
                "class": "Provider",
            },
            {
                "name": "bad",
                "type": "python",
                "module": "my_memory.provider",
                "class": " ",
            },
        ],
    )
    def test_validate_memory_requires_python_provider_target(
        self, provider: dict
    ) -> None:
        with pytest.raises(
            ConfigError,
            match="python provider requires module and class",
        ):
            validate_memory({"providers": [provider]})

    def test_validate_memory_rejects_duplicate_provider_names(self) -> None:
        with pytest.raises(ConfigError, match="duplicate name"):
            validate_memory({
                "providers": [
                    {"name": "dup", "type": "builtin.markdown"},
                    {"name": "dup", "type": "python", "module": "x", "class": "Y"},
                ],
            })


class TestMemoryConfig:
    def test_project_config_without_memory_does_not_override_home_memory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        project = tmp_path / "project"
        home_cfg = home / ".mozilcode" / "config.yaml"
        project_cfg = project / ".mozilcode" / "config.yaml"
        home_cfg.parent.mkdir(parents=True)
        project_cfg.parent.mkdir(parents=True)
        home_cfg.write_text(
            "providers:\n"
            "  - name: home\n"
            "    protocol: openai\n"
            "    base_url: http://home.local/v1\n"
            "    model: gpt-home\n"
            "memory:\n"
            "  enabled: false\n",
            encoding="utf-8",
        )
        project_cfg.write_text(
            "providers:\n"
            "  - name: project\n"
            "    protocol: openai\n"
            "    base_url: http://project.local/v1\n"
            "    model: gpt-project\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        monkeypatch.chdir(project)

        cfg = load_config()

        assert cfg.providers[0].name == "project"
        assert cfg.memory.enabled is False
