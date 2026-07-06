from __future__ import annotations

import pytest
from pydantic import ValidationError

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
