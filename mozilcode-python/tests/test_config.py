"""配置加载、合并与 schema 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mozilcode.config import ConfigError, load_config
from mozilcode.config.removed_capabilities import (
    REMOVED_CONFIG_SECTIONS,
    assert_no_removed_route_paths,
    find_removed_config_sections,
    find_removed_route_paths,
    removed_route_terms,
)
from mozilcode.config.validator import (
    REMOVED_CONFIG_SECTIONS as VALIDATOR_REMOVED_CONFIG_SECTIONS,
)


def _write_config(path: Path, extra: str = "", provider_name: str = "test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "providers:\n"
        f"  - name: {provider_name}\n"
        "    protocol: openai\n"
        f"    base_url: http://{provider_name}.local/v1\n"
        f"    model: {provider_name}-model\n"
        f"{extra}",
        encoding="utf-8",
    )


def test_project_config_can_explicitly_disable_home_booleans(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"

    _write_config(
        home / ".mozilcode" / "config.yaml",
        "permission_mode: plan\n"
        "enable_fork: true\n"
        "enable_verification_agent: true\n"
        "teammate_mode: in-process\n"
        "enable_coordinator_mode: true\n",
        provider_name="home",
    )
    _write_config(
        project / ".mozilcode" / "config.yaml",
        "permission_mode: default\n"
        "enable_fork: false\n"
        "enable_verification_agent: false\n"
        "teammate_mode: ''\n"
        "enable_coordinator_mode: false\n",
        provider_name="project",
    )

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(project)

    cfg = load_config()

    assert cfg.providers[0].name == "project"
    assert cfg.permission_mode == "default"
    assert cfg.enable_fork is False
    assert cfg.enable_verification_agent is False
    assert cfg.teammate_mode == ""
    assert cfg.enable_coordinator_mode is False


def test_project_config_without_team_fields_keeps_home_values(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"

    _write_config(
        home / ".mozilcode" / "config.yaml",
        "permission_mode: plan\n"
        "enable_fork: true\n"
        "enable_verification_agent: true\n"
        "teammate_mode: in-process\n"
        "enable_coordinator_mode: true\n",
        provider_name="home",
    )
    _write_config(project / ".mozilcode" / "config.yaml", provider_name="project")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(project)

    cfg = load_config()

    assert cfg.providers[0].name == "project"
    assert cfg.permission_mode == "plan"
    assert cfg.enable_fork is True
    assert cfg.enable_verification_agent is True
    assert cfg.teammate_mode == "in-process"
    assert cfg.enable_coordinator_mode is True


def test_project_worktree_config_overrides_home_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"

    _write_config(
        home / ".mozilcode" / "config.yaml",
        "worktree:\n"
        "  symlink_directories:\n"
        "    - home_modules\n"
        "  stale_cleanup_interval: 7200\n"
        "  stale_cutoff_hours: 48\n",
        provider_name="home",
    )
    _write_config(
        project / ".mozilcode" / "config.yaml",
        "worktree:\n"
        "  symlink_directories:\n"
        "    - project_modules\n"
        "  stale_cleanup_interval: 1800\n"
        "  stale_cutoff_hours: 6\n",
        provider_name="project",
    )

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(project)

    cfg = load_config()

    assert cfg.worktree.symlink_directories == ["project_modules"]
    assert cfg.worktree.stale_cleanup_interval == 1800
    assert cfg.worktree.stale_cutoff_hours == 6


def test_local_config_can_override_without_redeclaring_providers(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"

    _write_config(
        project / ".mozilcode" / "config.yaml",
        "permission_mode: default\n"
        "mcp_servers:\n"
        "  - name: local-tools\n"
        "    command: old-command\n",
        provider_name="project",
    )
    (project / ".mozilcode" / "config.local.yaml").write_text(
        "permission_mode: plan\n"
        "mcp_servers:\n"
        "  - name: local-tools\n"
        "    command: new-command\n"
        "memory:\n"
        "  enabled: false\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.chdir(project)

    cfg = load_config()

    assert cfg.providers[0].name == "project"
    assert cfg.permission_mode == "plan"
    assert [(server.name, server.command) for server in cfg.mcp_servers] == [
        ("local-tools", "new-command")
    ]
    assert cfg.memory.enabled is False


def test_merged_config_still_requires_at_least_one_provider(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    local_config = project / ".mozilcode" / "config.local.yaml"
    local_config.parent.mkdir(parents=True, exist_ok=True)
    local_config.write_text("permission_mode: plan\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.chdir(project)

    with pytest.raises(ConfigError, match="At least one provider"):
        load_config()


def test_explicit_config_file_still_requires_providers(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("permission_mode: plan\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Config must contain a 'providers' list"):
        load_config(config_path)


def test_removed_config_sections_are_reported_in_stable_order() -> None:
    assert find_removed_config_sections(
        {"providers": [], "gui": {}, "cloud": {}, "memory": {}}
    ) == ("cloud", "gui")


def test_validator_keeps_removed_config_sections_export() -> None:
    assert VALIDATOR_REMOVED_CONFIG_SECTIONS is REMOVED_CONFIG_SECTIONS


def test_removed_route_terms_are_matched_as_path_tokens() -> None:
    assert removed_route_terms("/api/cloud/status") == ("cloud",)
    assert removed_route_terms("/api/session/{sid}/status") == ()


def test_removed_route_paths_are_reported_in_stable_order() -> None:
    assert find_removed_route_paths(
        ["/api/health", "/cloud", "/api/settings/gui", "/api/session/{sid}"]
    ) == ("/cloud", "/api/settings/gui")


def test_removed_route_guard_rejects_product_surfaces() -> None:
    with pytest.raises(RuntimeError, match="Removed GUI/cloud/bot route"):
        assert_no_removed_route_paths(["/api/health", "/api/auth/login"])


@pytest.mark.parametrize("section", sorted(REMOVED_CONFIG_SECTIONS))
def test_removed_gui_cloud_bot_config_sections_are_rejected(
    tmp_path: Path, section: str
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, f"{section}:\n  enabled: true\n")

    with pytest.raises(ConfigError, match="Removed config section"):
        load_config(config_path)
