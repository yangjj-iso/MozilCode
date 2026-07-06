from __future__ import annotations

from pathlib import Path

from mozilcode.skills.tool_schema import (
    clean_tool_schema,
    is_valid_tool_name,
    normalize_tool_schemas,
)


def test_is_valid_tool_name_accepts_python_identifier_style_names() -> None:
    assert is_valid_tool_name("parse_resume")
    assert is_valid_tool_name("_internal_tool")
    assert is_valid_tool_name("T1")


def test_is_valid_tool_name_rejects_unsafe_or_empty_names() -> None:
    assert not is_valid_tool_name("")
    assert not is_valid_tool_name("../escape")
    assert not is_valid_tool_name("bad-name")
    assert not is_valid_tool_name("1starts_with_digit")


def test_clean_tool_schema_keeps_description_and_schema_fields(tmp_path: Path) -> None:
    schema = clean_tool_schema(
        {
            "name": "lookup",
            "description": "Lookup data",
            "parameters": {"type": "object"},
        },
        tmp_path / "tool.json",
        1,
    )

    assert schema == {
        "name": "lookup",
        "description": "Lookup data",
        "parameters": {"type": "object"},
    }


def test_clean_tool_schema_rejects_bad_description_or_input_schema(
    tmp_path: Path,
) -> None:
    assert clean_tool_schema(
        {"name": "bad_description", "description": []},
        tmp_path / "tool.json",
        1,
    ) is None
    assert clean_tool_schema(
        {"name": "bad_schema", "description": "bad", "input_schema": []},
        tmp_path / "tool.json",
        2,
    ) is None


def test_normalize_tool_schemas_accepts_single_object_and_skips_duplicates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tool.json"

    assert normalize_tool_schemas(
        {"name": "single", "description": "One tool"},
        path,
    ) == [{"name": "single", "description": "One tool"}]

    assert normalize_tool_schemas(
        [
            {"name": "same", "description": "first"},
            {"name": "same", "description": "second"},
            "bad",
            {"name": "../escape", "description": "bad"},
        ],
        path,
    ) == [{"name": "same", "description": "first"}]
