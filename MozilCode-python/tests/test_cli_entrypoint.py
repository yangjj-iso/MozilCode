from __future__ import annotations

import sys

import pytest

from mozilcode import __main__ as cli


def test_main_without_prompt_rejects_removed_interactive_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["mozilcode"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Interactive GUI/TUI mode has been removed" in err
