# MozilCode Python

This package contains the MozilCode core runtime, CLI, daemon server, tools, MCP integration, and tests.

## Development

Run the non-daemon test suite:

```powershell
uv run pytest -q -k "not daemon"
```

Run the CLI:

```powershell
uv run mozilcode
```

Run the local daemon:

```powershell
uv run mozilcode-daemon
```

The daemon listens on `127.0.0.1:7800` by default.

## A2A

The daemon exposes a non-streaming local A2A bridge:

- Agent card: `GET http://127.0.0.1:7800/.well-known/agent-card.json`
- JSON-RPC: `POST http://127.0.0.1:7800/a2a/rpc`

GUI and external bot/cloud adapters are intentionally not part of this package.

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
