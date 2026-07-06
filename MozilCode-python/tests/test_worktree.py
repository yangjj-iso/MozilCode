"""Git Worktree 管理系统的测试（第 13 章）。"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from mozilcode.cache import FileCache
from mozilcode.config import ConfigError, WorktreeConfig, load_config
from mozilcode.worktree.changes import count_worktree_changes, has_worktree_changes
from mozilcode.worktree.integration import build_worktree_notice, generate_worktree_name
from mozilcode.worktree.manager import WorktreeError, WorktreeManager
from mozilcode.worktree.models import WorktreeSession
from mozilcode.worktree.session import load_worktree_session, save_worktree_session
from mozilcode.worktree.slug import flatten_slug, validate_slug

# =========================================================================
# A. Slug 校验
# =========================================================================

class TestValidateSlug:
    def test_valid_simple(self):
        assert validate_slug("my-feature") is None

    def test_valid_with_dots(self):
        assert validate_slug("v1.0") is None

    def test_valid_nested(self):
        assert validate_slug("team/alice") is None

    def test_valid_single_char(self):
        assert validate_slug("a") is None

    def test_valid_underscores(self):
        assert validate_slug("my_feature_2") is None

    def test_empty(self):
        assert validate_slug("") is not None

    def test_too_long(self):
        assert validate_slug("a" * 65) is not None
        assert validate_slug("a" * 64) is None

    def test_path_traversal(self):
        assert validate_slug("../../etc/passwd") is not None

    def test_dot_segment(self):
        assert validate_slug("foo/./bar") is not None
        assert validate_slug("foo/../bar") is not None

    def test_dot_only(self):
        assert validate_slug(".") is not None
        assert validate_slug("..") is not None

    def test_spaces(self):
        assert validate_slug("my feature") is not None

    def test_special_chars(self):
        assert validate_slug("my@feature") is not None
        assert validate_slug("my feature") is not None
        assert validate_slug("my;feature") is not None

    def test_empty_segment(self):
        assert validate_slug("foo//bar") is not None

class TestFlattenSlug:
    def test_no_slash(self):
        assert flatten_slug("my-feature") == "my-feature"

    def test_with_slash(self):
        assert flatten_slug("team/alice") == "team+alice"

    def test_multiple_slashes(self):
        assert flatten_slug("a/b/c") == "a+b+c"

# =========================================================================
# B. FileCache
# =========================================================================

class TestFileCache:
    def test_put_and_get(self):
        cache = FileCache()
        cache.put("/tmp/test.py", "content")
        assert cache.get("/tmp/test.py") == "content"

    def test_miss(self):
        cache = FileCache()
        assert cache.get("/nonexistent") is None

    def test_invalidate(self):
        cache = FileCache()
        cache.put("/tmp/test.py", "content")
        cache.invalidate("/tmp/test.py")
        assert cache.get("/tmp/test.py") is None

    def test_clear(self):
        cache = FileCache()
        cache.put("/a", "1")
        cache.put("/b", "2")
        assert len(cache) == 2
        cache.clear()
        assert len(cache) == 0
        assert cache.get("/a") is None

    def test_invalidate_nonexistent(self):
        cache = FileCache()
        cache.invalidate("/nonexistent")  # 不应抛出异常

# =========================================================================
# C. 配置扩展
# =========================================================================

class TestWorktreeConfig:
    def test_defaults(self):
        cfg = WorktreeConfig()
        assert "node_modules" in cfg.symlink_directories
        assert cfg.stale_cleanup_interval == 3600
        assert cfg.stale_cutoff_hours == 24

    def test_load_config_without_worktree_section(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "providers:\n"
            "  - name: test\n"
            "    protocol: openai\n"
            "    base_url: http://localhost\n"
            "    model: gpt-4\n"
        )
        cfg = load_config(config_file)
        assert cfg.worktree.stale_cleanup_interval == 3600

    def test_load_config_with_worktree_section(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "providers:\n"
            "  - name: test\n"
            "    protocol: openai\n"
            "    base_url: http://localhost\n"
            "    model: gpt-4\n"
            "worktree:\n"
            "  symlink_directories:\n"
            "    - .venv\n"
            "  stale_cleanup_interval: 1800\n"
            "  stale_cutoff_hours: 12\n"
        )
        cfg = load_config(config_file)
        assert cfg.worktree.symlink_directories == [".venv"]
        assert cfg.worktree.stale_cleanup_interval == 1800
        assert cfg.worktree.stale_cutoff_hours == 12

    @pytest.mark.parametrize(
        "field",
        ["stale_cleanup_interval", "stale_cutoff_hours"],
    )
    def test_worktree_integer_fields_reject_bool(self, tmp_path, field):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "providers:\n"
            "  - name: test\n"
            "    protocol: openai\n"
            "    base_url: http://localhost\n"
            "    model: gpt-4\n"
            "worktree:\n"
            f"  {field}: true\n"
        )

        with pytest.raises(ConfigError, match=field):
            load_config(config_file)

# =========================================================================
# H. 会话持久化
# =========================================================================

class TestSessionPersistence:

    def test_save_and_load(self, tmp_path):
        session = WorktreeSession(
            original_cwd="/original",
            worktree_path="/wt/path",
            worktree_name="my-feature",
            original_branch="main",
            original_head_commit="abc123",
        )
        save_worktree_session(tmp_path, session)
        loaded = load_worktree_session(tmp_path)
        assert loaded is not None
        assert loaded.worktree_name == "my-feature"
        assert loaded.original_cwd == "/original"

    def test_save_none_clears(self, tmp_path):
        session = WorktreeSession(
            original_cwd="/original",
            worktree_path="/wt/path",
            worktree_name="my-feature",
            original_branch="main",
            original_head_commit="abc123",
        )
        save_worktree_session(tmp_path, session)
        save_worktree_session(tmp_path, None)
        loaded = load_worktree_session(tmp_path)
        assert loaded is None

    def test_load_missing_file(self, tmp_path):
        assert load_worktree_session(tmp_path) is None

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "worktree_session.json"
        path.write_text("not json")
        assert load_worktree_session(tmp_path) is None

    def test_load_non_object_json(self, tmp_path):
        path = tmp_path / "worktree_session.json"
        path.write_text("[]", encoding="utf-8")
        assert load_worktree_session(tmp_path) is None

    def test_load_invalid_field_type(self, tmp_path):
        path = tmp_path / "worktree_session.json"
        path.write_text(
            json.dumps(
                {
                    "original_cwd": [],
                    "worktree_path": "/wt/path",
                    "worktree_name": "my-feature",
                    "original_branch": "main",
                    "original_head_commit": "abc123",
                }
            ),
            encoding="utf-8",
        )
        assert load_worktree_session(tmp_path) is None

# =========================================================================
# 集成辅助函数
# =========================================================================

class TestIntegrationHelpers:
    def test_generate_worktree_name(self):
        name = generate_worktree_name()
        assert name.startswith("agent-")
        assert len(name) == 14  # "agent-" + 8 个十六进制字符

    def test_build_worktree_notice(self):
        notice = build_worktree_notice("/parent/dir", "/wt/dir")
        assert "/parent/dir" in notice
        assert "/wt/dir" in notice
        assert "WORKTREE CONTEXT" in notice

# =========================================================================
# D. WorktreeManager（需要真实的 git 仓库）
# =========================================================================

def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)
    (path / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), capture_output=True)

@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    return repo

@pytest.fixture
def manager(git_repo):
    return WorktreeManager(
        repo_root=str(git_repo),
        symlink_directories=[],
    )


def _run(coro):
    return asyncio.run(coro)


class TestWorktreeManager:
    def test_create(self, manager, git_repo):
        wt = _run(manager.create("test-feature"))
        assert wt.name == "test-feature"
        assert wt.branch == "worktree-test-feature"
        assert Path(wt.path).exists()
        assert (Path(wt.path) / "README.md").exists()

    def test_create_invalid_slug(self, manager):
        with pytest.raises(WorktreeError, match="must not contain"):
            _run(manager.create("../escape"))

    def test_create_duplicate(self, manager):
        _run(manager.create("dup"))
        with pytest.raises(WorktreeError, match="already exists"):
            _run(manager.create("dup"))

    def test_create_nested_slug(self, manager):
        wt = _run(manager.create("team/alice"))
        assert wt.branch == "worktree-team+alice"
        assert Path(wt.path).exists()

    def test_fast_recovery(self, manager):
        wt1 = _run(manager.create("recover"))
        path = wt1.path
        manager.active.clear()
        wt2 = _run(manager.create("recover"))
        assert wt2.path == path
        assert wt2.head_commit == wt1.head_commit

    def test_enter_and_session(self, manager):
        _run(manager.create("enter-test"))
        session = _run(manager.enter("enter-test"))
        assert session.worktree_name == "enter-test"
        assert manager.current_session is not None

    def test_enter_sets_current_session(self, manager):
        _run(manager.create("cache-test"))
        session = _run(manager.enter("cache-test"))
        assert manager.current_session == session

    def test_enter_records_repo_root_not_process_cwd(self, manager, tmp_path, monkeypatch):
        _run(manager.create("cwd-source"))
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.chdir(outside)

        session = _run(manager.enter("cwd-source"))

        assert session.original_cwd == manager.repo_root

    def test_exit_keep(self, manager):
        _run(manager.create("exit-keep"))
        _run(manager.enter("exit-keep"))
        _run(manager.exit("exit-keep", action="keep"))
        assert manager.current_session is None
        assert "exit-keep" in manager.active

    def test_exit_requires_active_session(self, manager):
        _run(manager.create("exit-no-session"))
        with pytest.raises(WorktreeError, match="not in a worktree"):
            _run(manager.exit("exit-no-session"))

    def test_exit_requires_current_worktree(self, manager):
        _run(manager.create("exit-current"))
        _run(manager.create("exit-other"))
        _run(manager.enter("exit-current"))

        with pytest.raises(WorktreeError, match="not in worktree: exit-other"):
            _run(manager.exit("exit-other"))

        assert manager.current_session is not None
        assert manager.current_session.worktree_name == "exit-current"

    def test_exit_rejects_invalid_action(self, manager):
        _run(manager.create("exit-invalid-action"))
        _run(manager.enter("exit-invalid-action"))

        with pytest.raises(WorktreeError, match="invalid worktree exit action: archive"):
            _run(manager.exit("exit-invalid-action", action="archive"))

    def test_exit_remove_clean(self, manager):
        wt = _run(manager.create("exit-rm"))
        _run(manager.enter("exit-rm"))
        _run(manager.exit("exit-rm", action="remove", discard_changes=True))
        assert "exit-rm" not in manager.active

    def test_exit_remove_with_changes_blocked(self, manager, git_repo):
        wt = _run(manager.create("exit-protect"))
        (Path(wt.path) / "new_file.txt").write_text("changes")
        _run(manager.enter("exit-protect"))
        with pytest.raises(WorktreeError, match="has changes"):
            _run(manager.exit("exit-protect", action="remove", discard_changes=False))

    def test_list_worktrees(self, manager):
        _run(manager.create("list-a"))
        _run(manager.create("list-b"))
        wts = manager.list_worktrees()
        names = {wt.name for wt in wts}
        assert names == {"list-a", "list-b"}

    def test_enter_nonexistent(self, manager):
        with pytest.raises(WorktreeError, match="not found"):
            _run(manager.enter("nope"))

    def test_restore_session_rejects_invalid_persisted_name(self, manager):
        session = WorktreeSession(
            original_cwd=manager.repo_root,
            worktree_path=str(Path(manager.worktree_dir) / "bad"),
            worktree_name="../bad",
            original_branch="main",
            original_head_commit="abc123",
        )
        save_worktree_session(Path(manager.repo_root) / ".mozilcode", session)

        assert manager.restore_session() is None
        assert load_worktree_session(Path(manager.repo_root) / ".mozilcode") is None

    def test_restore_session_rejects_path_outside_managed_worktree_dir(
        self,
        manager,
        tmp_path,
        monkeypatch,
    ):
        session = WorktreeSession(
            original_cwd=manager.repo_root,
            worktree_path=str(tmp_path / "outside-worktree"),
            worktree_name="outside",
            original_branch="main",
            original_head_commit="abc123",
        )
        save_worktree_session(Path(manager.repo_root) / ".mozilcode", session)
        monkeypatch.setattr(
            WorktreeManager,
            "read_worktree_head_sha",
            staticmethod(lambda _path: "a" * 40),
        )

        assert manager.restore_session() is None
        assert load_worktree_session(Path(manager.repo_root) / ".mozilcode") is None

# =========================================================================
# F. 变更检测与自动清理
# =========================================================================

class TestChangeDetection:
    def test_clean_worktree(self, manager):
        wt = _run(manager.create("clean-wt"))
        assert not has_worktree_changes(wt.path, wt.head_commit)

    def test_uncommitted_changes(self, manager):
        wt = _run(manager.create("dirty-wt"))
        (Path(wt.path) / "dirty.txt").write_text("new")
        assert has_worktree_changes(wt.path, wt.head_commit)

    def test_new_commits(self, manager):
        wt = _run(manager.create("commit-wt"))
        assert wt.head_commit, "head_commit should not be empty after create"
        (Path(wt.path) / "committed.txt").write_text("new")
        subprocess.run(["git", "add", "."], cwd=wt.path, capture_output=True, check=True)
        result = subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=t@t",
             "commit", "-m", "test"],
            cwd=wt.path, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"commit failed: {result.stderr}"
        changes = count_worktree_changes(wt.path, wt.head_commit)
        assert changes.new_commits > 0

    def test_auto_cleanup_removes_clean(self, manager):
        wt = _run(manager.create("auto-clean"))
        result = _run(manager.auto_cleanup("auto-clean", wt.head_commit))
        assert not result.kept
        assert "auto-clean" not in manager.active

    def test_auto_cleanup_keeps_dirty(self, manager):
        wt = _run(manager.create("auto-dirty"))
        (Path(wt.path) / "file.txt").write_text("content")
        result = _run(manager.auto_cleanup("auto-dirty", wt.head_commit))
        assert result.kept
        assert result.path == wt.path
        assert "auto-dirty" in manager.active

# =========================================================================
# D4. read_worktree_head_sha
# =========================================================================

class TestReadWorktreeHeadSha:
    def test_valid_worktree(self, manager):
        wt = _run(manager.create("sha-test"))
        sha = WorktreeManager.read_worktree_head_sha(wt.path)
        assert sha is not None
        assert len(sha) == 40

    def test_nonexistent_dir(self):
        sha = WorktreeManager.read_worktree_head_sha("/nonexistent/path")
        assert sha is None

    def test_not_a_worktree(self, tmp_path):
        sha = WorktreeManager.read_worktree_head_sha(str(tmp_path))
        assert sha is None
