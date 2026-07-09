"""Configuration loading, validation, and schema."""

from mozilcode.config.core import (
    AppConfig,
    ConfigError,
    MCPServerConfig,
    MemoryConfig,
    MemoryProviderConfig,
    ProviderConfig,
    WorktreeConfig,
    build_child_env,
    load_config,
    resolve_env_vars,
)
from mozilcode.config.model_context import (
    DEFAULT_CONTEXT_WINDOW,
    MODEL_CONTEXT_WINDOWS,
    lookup_model_context_window,
)
from mozilcode.config.removed_capabilities import (
    REMOVED_CONFIG_SECTIONS,
    find_removed_config_sections,
)
from mozilcode.config.validator import (
    VALID_PERMISSION_MODES,
    VALID_PROTOCOLS,
    VALID_TEAMMATE_MODES,
    validate_memory,
    validate_mcp_servers,
    validate_permission_mode,
    validate_providers,
    validate_worktree,
)

__all__ = [
    "AppConfig",
    "ConfigError",
    "DEFAULT_CONTEXT_WINDOW",
    "MCPServerConfig",
    "MODEL_CONTEXT_WINDOWS",
    "MemoryConfig",
    "MemoryProviderConfig",
    "ProviderConfig",
    "REMOVED_CONFIG_SECTIONS",
    "VALID_PERMISSION_MODES",
    "VALID_PROTOCOLS",
    "VALID_TEAMMATE_MODES",
    "WorktreeConfig",
    "build_child_env",
    "find_removed_config_sections",
    "load_config",
    "lookup_model_context_window",
    "resolve_env_vars",
    "validate_memory",
    "validate_mcp_servers",
    "validate_permission_mode",
    "validate_providers",
    "validate_worktree",
]
