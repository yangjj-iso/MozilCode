# MewCode

MewCode is split into three active parts:

- `MewCode-python`: Python core, daemon, tools, and tests.
- `mewcode-gui`: Vue + Tauri desktop GUI.
- `mewcode-cloud`: Java Spring Boot cloud service backed by MySQL.

## Common Commands

Python core:

```powershell
cd MewCode-python
uv run pytest -q -k "not daemon"
```

GUI:

```powershell
cd mewcode-gui
npm run build
```

The GUI connects to the local daemon at `http://127.0.0.1:7800` by default. Override it with:

```powershell
$env:VITE_MEWCODE_DAEMON_HTTP="http://127.0.0.1:7800"
$env:VITE_MEWCODE_DAEMON_WS="ws://127.0.0.1:7800"
```

Cloud service:

```powershell
cd mewcode-cloud
mvn package
```

The cloud service expects MySQL. Configure it with `MEWCODE_DB_URL`, `MEWCODE_DB_USER`, `MEWCODE_DB_PASSWORD`, and `MEWCODE_JWT_SECRET`.
