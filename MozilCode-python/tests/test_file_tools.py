from __future__ import annotations

import pytest
from pydantic import ValidationError

from mozilcode.tools.glob import Glob
from mozilcode.tools.glob import Params as GlobParams
from mozilcode.tools.grep import Grep
from mozilcode.tools.grep import Params as GrepParams
from mozilcode.tools.read_file import Params as ReadFileParams
from mozilcode.tools.read_file import ReadFile


@pytest.mark.asyncio
async def test_read_file_respects_offset_and_limit(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = await ReadFile().execute(
        ReadFileParams(file_path=str(target), offset=1, limit=1)
    )

    assert not result.is_error
    assert result.output == "2\ttwo"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"offset": -1, "limit": 1},
        {"offset": 0, "limit": 0},
        {"offset": 0, "limit": -1},
    ],
)
def test_read_file_params_reject_invalid_ranges(tmp_path, kwargs):
    target = tmp_path / "sample.txt"

    with pytest.raises(ValidationError):
        ReadFileParams(file_path=str(target), **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "limit", "message"),
    [
        (-1, 1, "offset must be non-negative"),
        (0, 0, "limit must be positive"),
    ],
)
async def test_read_file_execute_defensively_rejects_invalid_ranges(
    tmp_path,
    offset,
    limit,
    message,
):
    target = tmp_path / "sample.txt"
    target.write_text("one\ntwo\n", encoding="utf-8")
    params = ReadFileParams.model_construct(
        file_path=str(target),
        offset=offset,
        limit=limit,
    )

    result = await ReadFile().execute(params)

    assert result.is_error
    assert message in result.output


@pytest.mark.parametrize("params_type", [GrepParams, GlobParams])
def test_search_tool_params_reject_empty_patterns(params_type):
    with pytest.raises(ValidationError):
        params_type(pattern="")


@pytest.mark.asyncio
async def test_grep_finds_matches_with_include_filter(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("print('needle')\n", encoding="utf-8")
    ignored = tmp_path / "notes.txt"
    ignored.write_text("needle\n", encoding="utf-8")

    result = await Grep().execute(
        GrepParams(pattern="needle", path=str(tmp_path), include="*.py")
    )

    assert not result.is_error
    assert result.output == "source.py:1:print('needle')"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_type,params_type", [(Grep, GrepParams), (Glob, GlobParams)])
async def test_search_tools_reject_file_as_base_path(tmp_path, tool_type, params_type):
    target = tmp_path / "sample.txt"
    target.write_text("content\n", encoding="utf-8")

    result = await tool_type().execute(params_type(pattern="*", path=str(target)))

    assert result.is_error
    assert "path is not a directory" in result.output


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_type,params_type", [(Grep, GrepParams), (Glob, GlobParams)])
async def test_search_tools_defensively_reject_empty_patterns(
    tmp_path,
    tool_type,
    params_type,
):
    params = params_type.model_construct(pattern="", path=str(tmp_path))

    result = await tool_type().execute(params)

    assert result.is_error
    assert "pattern must not be empty" in result.output


@pytest.mark.asyncio
async def test_glob_returns_files_and_skips_generated_directories(tmp_path):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    source = source_dir / "main.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    skipped_dir = tmp_path / ".git"
    skipped_dir.mkdir()
    skipped = skipped_dir / "ignored.py"
    skipped.write_text("ignored\n", encoding="utf-8")

    result = await Glob().execute(GlobParams(pattern="**/*.py", path=str(tmp_path)))

    assert not result.is_error
    assert result.output.replace("\\", "/") == "src/main.py"
