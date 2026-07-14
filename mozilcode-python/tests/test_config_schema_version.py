"""配置 schema 版本与兼容性测试。"""

from __future__ import annotations

import pytest

from mozilcode.config import CURRENT_CONFIG_SCHEMA_VERSION, ConfigError
from mozilcode.config.validator import validate_config_structure


def _config(**extra):
    return {
        "providers": [
            {
                "name": "local",
                "protocol": "openai-compat",
                "base_url": "http://127.0.0.1:9999/v1",
                "model": "test-model",
            }
        ],
        **extra,
    }


def test_config_without_schema_version_uses_current_version() -> None:
    validated = validate_config_structure(_config())

    assert validated["schema_version"] == CURRENT_CONFIG_SCHEMA_VERSION


def test_future_config_schema_is_rejected() -> None:
    with pytest.raises(ConfigError, match="newer than supported"):
        validate_config_structure(
            _config(schema_version=CURRENT_CONFIG_SCHEMA_VERSION + 1)
        )


@pytest.mark.parametrize("value", [0, -1, True, "1"])
def test_invalid_config_schema_version_is_rejected(value) -> None:
    with pytest.raises(ConfigError, match="positive integer"):
        validate_config_structure(_config(schema_version=value))
