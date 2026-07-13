# MozilCode Python

This package contains the MozilCode core runtime, TUI/headless CLI, local daemon server, tools, MCP integration, and tests.

MozilCode is intentionally file-configured and local-first. The separate
`mewcode-gui` package provides the local Vue/Tauri interface; it connects only
to the local daemon. Configure model providers, MCP servers, hooks, skills, and
memory providers through `.mozilcode/config.yaml`.

## Development

Run the non-daemon test suite:

```powershell
uv run pytest -q -k "not daemon"
```

Run the headless CLI:

```powershell
uv run mozilcode -p "summarize this repository"
```

Plain `mozilcode` is intentionally headless; pass `-p` to run a prompt.

Run the local daemon:

```powershell
uv run mozilcode-daemon
```

The daemon listens on `127.0.0.1:7800` by default.

For the browser/Tauri GUI, the daemon allows only the local GUI origins by
default. Override the allowlist explicitly when using another frontend:

```powershell
$env:MOZILCODE_CORS_ORIGINS = "http://localhost:1420,http://127.0.0.1:1420,tauri://localhost"
uv run mozilcode-daemon
```

The daemon is intentionally local-first. Do not expose it beyond localhost
without adding an authenticated reverse proxy and a restricted CORS allowlist.

Optional local token authentication protects both HTTP and WebSocket APIs:

```powershell
$env:MOZILCODE_DAEMON_TOKEN = "replace-with-a-random-local-token"
uv run mozilcode-daemon
```

Set the same value as `VITE_MEWCODE_DAEMON_TOKEN` when building or running the
GUI. A token is mandatory if the daemon is configured to listen on a non-local
host.

From the workspace root, smoke-test a running daemon without making a model call:

```powershell
uv run python scripts/smoke_mozilcode_daemon.py --base-url http://127.0.0.1:7800
```

## A2A

The daemon exposes a non-streaming local A2A bridge:

- Agent card: `GET http://127.0.0.1:7800/.well-known/agent-card.json`
- JSON-RPC: `POST http://127.0.0.1:7800/a2a/rpc`

External bot adapters and hosted account integrations are intentionally not part of this package.

## Memory plugins

Long-term memory is routed through `MemoryHub`, with the legacy Markdown memory kept as the default provider. Custom memory systems can be added with `memory.providers` in `config.yaml` using `type: python`, `module`, and `class`.

Example custom provider configuration:

```yaml
memory:
  enabled: true
  providers:
    - name: markdown
      type: builtin.markdown
    - name: vector
      type: python
      module: my_memory.provider
      class: VectorMemoryProvider
      config:
        top_k: 8
```

See `mozilcode/docs/memory-plugins.md` for the provider protocol and configuration examples.
