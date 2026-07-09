"""MozilCode 的配置校验逻辑。"""

from __future__ import annotations

from mozilcode.config.model_context import (
    DEFAULT_CONTEXT_WINDOW,
    MODEL_CONTEXT_WINDOWS,
    lookup_model_context_window,
)
from mozilcode.config.removed_capabilities import (
    REMOVED_CONFIG_SECTIONS,
    find_removed_config_sections,
)

VALID_PROTOCOLS = {"anthropic", "openai", "openai-compat"}

VALID_PERMISSION_MODES = {
    "default",
    "acceptEdits",
    "plan",
    "bypassPermissions",
    "custom",
    "dontAsk",
}

VALID_TEAMMATE_MODES = {"", "in-process"}


class ConfigError(Exception):
    pass


def _required_name(raw_name: object, item_label: str) -> str:
    name = str(raw_name or "").strip()
    if not name:
        raise ConfigError(f"{item_label}: missing 'name'")
    return name


def _remember_unique_name(
    name: str,
    seen_names: set[str],
    *,
    item_label: str,
) -> None:
    if name in seen_names:
        raise ConfigError(f"{item_label} '{name}': duplicate name")
    seen_names.add(name)


def _required_string_field(entry: dict, field_name: str, item_label: str) -> str:
    value = entry[field_name]
    if not isinstance(value, str):
        raise ConfigError(f"{item_label}: {field_name} must be a string")
    value = value.strip()
    if not value:
        raise ConfigError(f"{item_label}: {field_name} must not be empty")
    return value


def _optional_string_field(entry: dict, field_name: str, item_label: str) -> str:
    value = entry.get(field_name, "")
    if not isinstance(value, str):
        raise ConfigError(f"{item_label}: {field_name} must be a string")
    return value.strip()


def _string_list_field(entry: dict, field_name: str, item_label: str) -> list[str]:
    value = entry.get(field_name, [])
    if not isinstance(value, list):
        raise ConfigError(f"{item_label}: {field_name} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{item_label}: {field_name} must be a list of strings")
    return value


def _string_mapping_field(entry: dict, field_name: str, item_label: str) -> dict[str, str]:
    value = entry.get(field_name, {})
    if not isinstance(value, dict):
        raise ConfigError(
            f"{item_label}: {field_name} must be a mapping of strings to strings"
        )
    if not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        raise ConfigError(
            f"{item_label}: {field_name} must be a mapping of strings to strings"
        )
    return value


def _integer_field(
    value: object,
    field_label: str,
    *,
    min_value: int,
    allow_zero: bool,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        requirement = "non-negative" if allow_zero else "positive"
        raise ConfigError(f"{field_label} must be a {requirement} integer")
    if allow_zero:
        if value < min_value:
            raise ConfigError(f"{field_label} must be a non-negative integer")
    elif value <= min_value:
        raise ConfigError(f"{field_label} must be a positive integer")
    return value


def reject_removed_config_sections(raw: dict) -> None:
    removed = find_removed_config_sections(raw)
    if not removed:
        return
    names = ", ".join(removed)
    raise ConfigError(
        f"Removed config section(s): {names}. "
        "MozilCode is headless and local-first; configure model providers, "
        "MCP, hooks, skills, and memory through config.yaml instead."
    )


def validate_providers(raw_providers: list) -> list[dict]:
    """校验 providers 列表，返回清洗后的 provider 字典列表。"""
    if not isinstance(raw_providers, list) or len(raw_providers) == 0:
        raise ConfigError("At least one provider must be configured")

    providers: list[dict] = []
    seen_names: set[str] = set()
    for i, entry in enumerate(raw_providers):
        if not isinstance(entry, dict):
            raise ConfigError(f"Provider #{i + 1}: must be a mapping")

        missing = [f for f in ("name", "protocol", "base_url", "model") if f not in entry]
        if missing:
            raise ConfigError(f"Provider #{i + 1}: missing fields: {', '.join(missing)}")

        name = _required_name(entry["name"], f"Provider #{i + 1}")
        _remember_unique_name(name, seen_names, item_label="Provider")

        item_label = f"Provider #{i + 1}"
        protocol = _required_string_field(entry, "protocol", item_label)
        if protocol not in VALID_PROTOCOLS:
            raise ConfigError(
                f"Provider #{i + 1}: invalid protocol '{protocol}', "
                f"must be one of: {', '.join(sorted(VALID_PROTOCOLS))}"
            )
        base_url = _required_string_field(entry, "base_url", item_label)
        model = _required_string_field(entry, "model", item_label)
        api_key = _optional_string_field(entry, "api_key", item_label)

        # 默认为 0（"未设置"）而非硬编码的 window 值：0 会让
        # ProviderConfig.get_context_window() 走四层回退链解析
        #（自动拉取 / 映射表 / 默认值）。配置中显式指定的值仍须为正整数，
        # 且作为最高优先级覆盖。
        context_window = entry.get("context_window", 0)
        context_window = _integer_field(
            context_window,
            f"Provider #{i + 1}: context_window",
            min_value=0,
            allow_zero=True,
        )

        thinking = entry.get("thinking", False)
        if not isinstance(thinking, bool):
            raise ConfigError(f"Provider #{i + 1}: thinking must be a boolean")

        max_output_tokens = entry.get("max_output_tokens", 0)
        max_output_tokens = _integer_field(
            max_output_tokens,
            f"Provider #{i + 1}: max_output_tokens",
            min_value=0,
            allow_zero=True,
        )

        providers.append(
            {
                "name": name,
                "protocol": protocol,
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
                "thinking": thinking,
                "context_window": context_window,
                "max_output_tokens": max_output_tokens,
            }
        )

    return providers


def validate_permission_mode(mode: str) -> str:
    """校验 permission_mode 取值。"""
    if mode not in VALID_PERMISSION_MODES:
        raise ConfigError(
            f"Invalid permission_mode '{mode}', "
            f"must be one of: {', '.join(sorted(VALID_PERMISSION_MODES))}"
        )
    return mode


def validate_mcp_servers(raw_mcp: list | None) -> list[dict]:
    """校验 mcp_servers 配置段，返回清洗后的 server 配置字典列表。"""
    if raw_mcp is None:
        return []

    if not isinstance(raw_mcp, list):
        raise ConfigError("'mcp_servers' must be a list of server configs")

    servers: list[dict] = []
    seen_names: set[str] = set()
    for i, entry in enumerate(raw_mcp):
        if not isinstance(entry, dict):
            raise ConfigError(f"MCP server #{i + 1}: must be a mapping")
        item_label = f"MCP server #{i + 1}"
        name = _required_name(entry.get("name"), item_label)
        _remember_unique_name(name, seen_names, item_label="MCP server")
        has_command = "command" in entry
        has_url = "url" in entry
        if has_command and has_url:
            raise ConfigError(
                f"MCP server '{name}': cannot have both 'command' and 'url'"
            )
        if not has_command and not has_url:
            raise ConfigError(
                f"MCP server '{name}': must have either 'command' or 'url'"
            )
        command = (
            _required_string_field(entry, "command", item_label)
            if has_command
            else None
        )
        url = _required_string_field(entry, "url", item_label) if has_url else None
        servers.append(
            {
                "name": name,
                "command": command,
                "args": _string_list_field(entry, "args", item_label),
                "url": url,
                "headers": _string_mapping_field(entry, "headers", item_label),
                "env": _string_mapping_field(entry, "env", item_label),
            }
        )

    return servers


def validate_hooks(raw_hooks: list | None) -> list:
    """校验 hooks 配置段。"""
    if raw_hooks is None:
        return []
    if not isinstance(raw_hooks, list):
        raise ConfigError("'hooks' must be a list of hook definitions")
    return raw_hooks


def validate_memory(raw_memory: object) -> dict:
    """校验 memory 配置段，返回标准化配置。"""
    defaults = {
        "enabled": True,
        "providers": [
            {
                "name": "markdown",
                "type": "builtin.markdown",
                "enabled": True,
                "config": {},
                "module": "",
                "class": "",
            }
        ],
    }
    if raw_memory is None:
        return defaults
    if not isinstance(raw_memory, dict):
        raise ConfigError("'memory' must be a mapping")

    enabled = raw_memory.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError("'memory.enabled' must be a boolean")

    raw_providers = raw_memory.get("providers", defaults["providers"])
    if raw_providers is None:
        raw_providers = []
    if not isinstance(raw_providers, list):
        raise ConfigError("'memory.providers' must be a list")

    providers: list[dict] = []
    seen_names: set[str] = set()
    for i, entry in enumerate(raw_providers):
        if not isinstance(entry, dict):
            raise ConfigError(f"Memory provider #{i + 1}: must be a mapping")
        item_label = f"Memory provider #{i + 1}"
        name = _required_name(entry.get("name"), item_label)
        _remember_unique_name(name, seen_names, item_label="Memory provider")
        if "type" not in entry:
            raise ConfigError(f"Memory provider '{name}': missing 'type'")
        provider_label = f"Memory provider '{name}'"
        provider_type = _required_string_field(entry, "type", provider_label)
        provider_enabled = entry.get("enabled", True)
        if not isinstance(provider_enabled, bool):
            raise ConfigError(f"Memory provider '{name}': 'enabled' must be a boolean")
        provider_config = entry.get("config", {})
        if not isinstance(provider_config, dict):
            raise ConfigError(f"Memory provider '{name}': 'config' must be a mapping")
        module = _optional_string_field(entry, "module", provider_label)
        class_name = ""
        if "class" in entry:
            class_name = _optional_string_field(entry, "class", provider_label)
        if not class_name and "class_name" in entry:
            class_name = _optional_string_field(entry, "class_name", provider_label)
        if provider_type == "python" and (not module or not class_name):
            raise ConfigError(
                f"Memory provider '{name}': python provider requires module and class"
            )

        providers.append(
            {
                "name": name,
                "type": provider_type,
                "enabled": provider_enabled,
                "config": provider_config,
                "module": module,
                "class": class_name,
            }
        )

    return {"enabled": enabled, "providers": providers}


def validate_bool_field(value: object, field_name: str) -> bool:
    """校验一个布尔类型的配置字段。"""
    if not isinstance(value, bool):
        raise ConfigError(f"'{field_name}' must be a boolean")
    return value


def validate_worktree(raw_wt: dict | None) -> dict:
    """校验 worktree 配置段，返回清洗后的配置字典。"""
    defaults = {
        "symlink_directories": ["node_modules", ".venv", "vendor"],
        "stale_cleanup_interval": 3600,
        "stale_cutoff_hours": 24,
    }

    if raw_wt is None:
        return defaults

    if not isinstance(raw_wt, dict):
        raise ConfigError("'worktree' must be a mapping")

    sym = raw_wt.get("symlink_directories", defaults["symlink_directories"])
    if not isinstance(sym, list) or not all(isinstance(s, str) for s in sym):
        raise ConfigError("'worktree.symlink_directories' must be a list of strings")

    interval = raw_wt.get("stale_cleanup_interval", defaults["stale_cleanup_interval"])
    interval = _integer_field(
        interval,
        "'worktree.stale_cleanup_interval'",
        min_value=0,
        allow_zero=False,
    )

    cutoff = raw_wt.get("stale_cutoff_hours", defaults["stale_cutoff_hours"])
    cutoff = _integer_field(
        cutoff,
        "'worktree.stale_cutoff_hours'",
        min_value=0,
        allow_zero=False,
    )

    return {
        "symlink_directories": sym,
        "stale_cleanup_interval": interval,
        "stale_cutoff_hours": cutoff,
    }


def validate_teammate_mode(mode: object) -> str:
    """校验 teammate_mode 取值。"""
    if not isinstance(mode, str) or mode not in VALID_TEAMMATE_MODES:
        raise ConfigError(
            f"Invalid teammate_mode '{mode}', "
            f"must be one of: {', '.join(repr(m) for m in sorted(VALID_TEAMMATE_MODES))}"
        )
    return mode


def validate_config_structure(raw: object, *, require_providers: bool = True) -> dict:
    """校验的主入口。校验解析后的原始配置，返回清洗后的字典。

    返回的字典包含以下键：
        providers、permission_mode、mcp_servers、hooks、
        enable_fork、enable_verification_agent、worktree、
        teammate_mode、enable_coordinator_mode
    """
    if not isinstance(raw, dict):
        raise ConfigError("Config must be a mapping")
    if require_providers and "providers" not in raw:
        raise ConfigError("Config must contain a 'providers' list")
    reject_removed_config_sections(raw)

    providers = validate_providers(raw["providers"]) if "providers" in raw else []

    return {
        "providers": providers,
        "permission_mode": validate_permission_mode(raw.get("permission_mode", "default")),
        "mcp_servers": validate_mcp_servers(raw.get("mcp_servers")),
        "hooks": validate_hooks(raw.get("hooks")),
        "memory": validate_memory(raw.get("memory")),
        "enable_fork": validate_bool_field(raw.get("enable_fork", False), "enable_fork"),
        "enable_verification_agent": validate_bool_field(
            raw.get("enable_verification_agent", False), "enable_verification_agent"
        ),
        "worktree": validate_worktree(raw.get("worktree")),
        "teammate_mode": validate_teammate_mode(raw.get("teammate_mode", "")),
        "enable_coordinator_mode": validate_bool_field(
            raw.get("enable_coordinator_mode", False), "enable_coordinator_mode"
        ),
    }
