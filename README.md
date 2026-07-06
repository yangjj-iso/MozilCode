# MozilCode

MozilCode is a Python-first local coding assistant:

- `MozilCode-python`: Python core, daemon, tools, and tests.

The workspace intentionally excludes GUI/front-end packages and cloud account integrations. Runtime configuration is file-based under `.mozilcode/config.yaml`.

## Common Commands

Python core:

```powershell
cd MozilCode-python
uv run pytest -q -k "not daemon"
```
