# MewCode Python

This package contains the MewCode core runtime, CLI, daemon server, tools, MCP integration, and tests.

## Development

Run the non-daemon test suite:

```powershell
uv run pytest -q -k "not daemon"
```

Run the CLI:

```powershell
uv run mewcode
```

Run the daemon used by the desktop GUI:

```powershell
uv run mewcode-daemon
```

The daemon listens on `127.0.0.1:7800` by default.
