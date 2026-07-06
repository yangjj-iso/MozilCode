from __future__ import annotations

from pathlib import Path

from mozilcode.config import load_config


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
