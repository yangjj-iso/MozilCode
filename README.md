# MozilCode

MozilCode is a local-first coding assistant:

- `mozilcode-python`: Python runtime, daemon, TUI, tools, and tests.
- `mozilcode-gui`: local Vue/Tauri desktop GUI for the daemon.

The local runtime is the primary product path and uses file-based configuration
under `.mozilcode/config.yaml`. The optional `mozilcode-cloud` directory is not
required to build or run the local assistant.

## Common Commands

Python core:

```powershell
cd mozilcode-python
uv run pytest -q -k "not daemon"
```

Local GUI:

```powershell
cd mozilcode-gui
npm install
npm run dev
```

Daemon smoke test for a running local daemon:

```powershell
uv run python scripts/smoke_mozilcode_daemon.py --base-url http://127.0.0.1:7800
```
