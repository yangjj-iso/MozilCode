from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .model_context import DEFAULT_CONTEXT_WINDOW, lookup_model_context_window
from .validator import (
    ConfigError,
    VALID_PERMISSION_MODES,
    VALID_PROTOCOLS,
    VALID_TEAMMATE_MODES,
    validate_config_structure,
)


_ENV_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai-compat": "OPENAI_API_KEY",
}

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


@dataclass
class ProviderConfig:
    name: str
    protocol: str
    base_url: str
    model: str
    api_key: str = ""
    thinking: bool = False
    # 0 表示"未设置" — get_context_window() 通过四层 fallback 解析真实窗口大小。
    # 正数表示配置文件里显式指定的覆盖值。
    context_window: int = 0
    max_output_tokens: int = 0
    # 运行时 cache，存放从 provider 的 /v1/models 端点自动拉取的 context window
    # （get_context_window 的第 2 层）。通过 set_fetched_context_window() 写入一次；
    # 0 表示"尚未拉取"。不会持久化。
    _fetched_context_window: int = field(default=0, repr=False)

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        env_var = _ENV_KEY_MAP.get(self.protocol, "")
        return os.environ.get(env_var, "")

    def set_fetched_context_window(self, window: int) -> None:
        """记录从 provider 自动拉取到的 context window（第 2 层）。

        非正数会被忽略，这样一次失败的拉取就不会污染 cache。在解析
        context window 时，每个 provider 只会调用一次。
        """
        if window > 0:
            self._fetched_context_window = window

    def get_context_window(self) -> int:
        """通过四层 fallback 解析模型的 context window，按优先级从高到低：

          1. 配置文件提供的 context_window（> 0）——显式覆盖，永远优先。
          2. 从 provider 的 /v1/models 端点自动拉取并通过 set_fetched_context_window
             缓存的值（只有 anthropic 协议的 provider 才会设置它；拉取失败或缺失时
             保持为 0 并跳过）。
          3. 内置的「模型名 -> window」映射表（按子串匹配）。
          4. 保守的默认值（claude -> 200000，其他 -> 128000）。
        """
        if self.context_window > 0:
            return self.context_window
        if self._fetched_context_window > 0:
            return self._fetched_context_window
        window = lookup_model_context_window(self.model)
        if window > 0:
            return window
        if "claude" in self.model.lower():
            return DEFAULT_CONTEXT_WINDOW
        return 128_000

    def get_max_output_tokens(self) -> int:
        if self.max_output_tokens > 0:
            return self.max_output_tokens
        if self.thinking:
            return 64000
        return 8192


def resolve_env_vars(value: str) -> str:
    return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def build_child_env(declared_env: dict[str, str] | None) -> dict[str, str]:
    env: dict[str, str] = {}
    path = os.environ.get("PATH", "")
    if path:
        env["PATH"] = path
    for key, value in (declared_env or {}).items():
        env[key] = resolve_env_vars(value)
    return env


@dataclass
class MCPServerConfig:
    name: str
    enabled: bool = True
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)


    @property
    def is_stdio(self) -> bool:
        return self.command is not None


@dataclass
class WorktreeConfig:
    symlink_directories: list[str] = field(default_factory=lambda: ["node_modules", ".venv", "vendor"])
    stale_cleanup_interval: int = 3600
    stale_cutoff_hours: int = 24


@dataclass
class MemoryProviderConfig:
    name: str
    type: str
    enabled: bool = True
    config: dict = field(default_factory=dict)
    module: str = ""
    class_name: str = ""


@dataclass
class MemoryConfig:
    enabled: bool = True
    providers: list[MemoryProviderConfig] = field(
        default_factory=lambda: [MemoryProviderConfig(name="markdown", type="builtin.markdown")]
    )


@dataclass
class AppConfig:
    providers: list[ProviderConfig]
    schema_version: int = 1
    permission_mode: str = "default"
    permission_mode_declared: bool = False
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    mcp_servers_declared: bool = False
    raw_hooks: list[dict] = field(default_factory=list)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    memory_declared: bool = False
    enable_fork: bool = False
    enable_fork_declared: bool = False
    enable_verification_agent: bool = False
    enable_verification_agent_declared: bool = False
    worktree: WorktreeConfig = field(default_factory=WorktreeConfig)
    worktree_declared: bool = False
    teammate_mode: str = ""
    teammate_mode_declared: bool = False
    enable_coordinator_mode: bool = False
    enable_coordinator_mode_declared: bool = False


def _load_single_file(path: Path, *, require_providers: bool = True) -> AppConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse config {path}: {e}") from e

    validated = validate_config_structure(raw, require_providers=require_providers)
    raw_keys = raw if isinstance(raw, dict) else {}
    memory_declared = "memory" in raw_keys

    providers = [
        ProviderConfig(
            name=p["name"],
            protocol=p["protocol"],
            base_url=p["base_url"],
            model=p["model"],
            api_key=p["api_key"],
            thinking=p["thinking"],
            context_window=p["context_window"],
            max_output_tokens=p["max_output_tokens"],
        )
        for p in validated["providers"]
    ]

    mcp_servers = [
        MCPServerConfig(
            name=s["name"],
            enabled=s["enabled"],
            command=s["command"],
            args=s["args"],
            url=s["url"],
            headers=s["headers"],
            env=s["env"],
        )
        for s in validated["mcp_servers"]
    ]

    wt = validated["worktree"]
    worktree_cfg = WorktreeConfig(
        symlink_directories=wt["symlink_directories"],
        stale_cleanup_interval=wt["stale_cleanup_interval"],
        stale_cutoff_hours=wt["stale_cutoff_hours"],
    )
    memory_cfg = MemoryConfig(
        enabled=validated["memory"]["enabled"],
        providers=[
            MemoryProviderConfig(
                name=p["name"],
                type=p["type"],
                enabled=p["enabled"],
                config=p["config"],
                module=p["module"],
                class_name=p["class"],
            )
            for p in validated["memory"]["providers"]
        ],
    )

    return AppConfig(
        providers=providers,
        schema_version=validated["schema_version"],
        permission_mode=validated["permission_mode"],
        permission_mode_declared="permission_mode" in raw_keys,
        mcp_servers=mcp_servers,
        mcp_servers_declared="mcp_servers" in raw_keys,
        raw_hooks=validated["hooks"],
        memory=memory_cfg,
        memory_declared=memory_declared,
        enable_fork=validated["enable_fork"],
        enable_fork_declared="enable_fork" in raw_keys,
        enable_verification_agent=validated["enable_verification_agent"],
        enable_verification_agent_declared="enable_verification_agent" in raw_keys,
        worktree=worktree_cfg,
        worktree_declared="worktree" in raw_keys,
        teammate_mode=validated["teammate_mode"],
        teammate_mode_declared="teammate_mode" in raw_keys,
        enable_coordinator_mode=validated["enable_coordinator_mode"],
        enable_coordinator_mode_declared="enable_coordinator_mode" in raw_keys,
    )


def _merge_config(base: AppConfig, override: AppConfig) -> AppConfig:
    if override.providers:
        base.providers = override.providers
    if override.permission_mode_declared:
        base.permission_mode = override.permission_mode

    if override.mcp_servers_declared:
        if not override.mcp_servers:
            base.mcp_servers = []
        else:
            by_name = {s.name: i for i, s in enumerate(base.mcp_servers)}
            for s in override.mcp_servers:
                if s.name in by_name:
                    base.mcp_servers[by_name[s.name]] = s
                else:
                    base.mcp_servers.append(s)
                    by_name[s.name] = len(base.mcp_servers) - 1
        base.mcp_servers_declared = True

    base.raw_hooks.extend(override.raw_hooks)
    if override.memory_declared:
        base.memory = override.memory
        base.memory_declared = True
    if override.enable_fork_declared:
        base.enable_fork = override.enable_fork
        base.enable_fork_declared = True
    if override.enable_verification_agent_declared:
        base.enable_verification_agent = override.enable_verification_agent
        base.enable_verification_agent_declared = True
    if override.worktree_declared:
        base.worktree = override.worktree
        base.worktree_declared = True
    if override.teammate_mode_declared:
        base.teammate_mode = override.teammate_mode
        base.teammate_mode_declared = True
    if override.enable_coordinator_mode_declared:
        base.enable_coordinator_mode = override.enable_coordinator_mode
        base.enable_coordinator_mode_declared = True
    return base


def load_config(path: Path | None = None) -> AppConfig:
    if path is not None:
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        return _load_single_file(path)

    cwd = Path.cwd()
    home = Path.home()
    candidates = [
        home / ".mozilcode" / "config.yaml",
        cwd / ".mozilcode" / "config.yaml",
        cwd / ".mozilcode" / "config.local.yaml",
    ]

    merged: AppConfig | None = None
    for p in candidates:
        if not p.exists():
            continue
        layer = _load_single_file(p, require_providers=False)
        if merged is None:
            merged = layer
        else:
            merged = _merge_config(merged, layer)

    if merged is None:
        raise ConfigError(
            "No config file found. Expected .mozilcode/config.yaml "
            "in project or ~/.mozilcode/config.yaml"
        )
    if not merged.providers:
        raise ConfigError("At least one provider must be configured")
    return merged
