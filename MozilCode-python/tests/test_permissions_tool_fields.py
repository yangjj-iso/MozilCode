from __future__ import annotations

from mozilcode.permissions.rules import (
    extract_content as extract_content_from_rules,
    extract_sandbox_path as extract_sandbox_path_from_rules,
)
from mozilcode.permissions.tool_fields import extract_content, extract_sandbox_path


def test_extract_content_uses_tool_specific_primary_field() -> None:
    assert extract_content("Bash", {"command": "git status"}) == "git status"
    assert extract_content("ReadFile", {"file_path": "README.md"}) == "README.md"
    assert extract_content("WriteFile", {"file_path": "out.txt"}) == "out.txt"
    assert extract_content("Glob", {"pattern": "**/*.py"}) == "**/*.py"
    assert extract_content("Grep", {"pattern": "TODO"}) == "TODO"


def test_extract_content_handles_missing_and_none_values() -> None:
    assert extract_content("Bash", {"command": None}) == ""
    assert extract_content("Unknown", {"command": "ignored"}) == ""


def test_extract_sandbox_path_uses_defaults_for_search_tools() -> None:
    assert extract_sandbox_path("Glob", {"pattern": "*.py"}) == "."
    assert extract_sandbox_path("Grep", {"pattern": "TODO", "path": "src"}) == "src"


def test_extract_sandbox_path_rejects_non_string_path_values() -> None:
    assert extract_sandbox_path("WriteFile", {"file_path": None}) == ""
    assert extract_sandbox_path("EditFile", {"file_path": []}) == ""
    assert extract_sandbox_path("Bash", {"command": "ls"}) is None


def test_rules_module_keeps_compatibility_reexports() -> None:
    assert extract_content_from_rules("Bash", {"command": "pwd"}) == "pwd"
    assert extract_sandbox_path_from_rules("ReadFile", {"file_path": "x"}) == "x"
