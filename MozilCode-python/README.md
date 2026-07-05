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

Run the daemon used by the desktop GUI:

```powershell
uv run mozilcode-daemon
```

The daemon listens on `127.0.0.1:7800` by default.

## A2A and QQ

The daemon also exposes a non-streaming A2A bridge:

- Agent card: `GET http://127.0.0.1:7800/.well-known/agent-card.json`
- JSON-RPC: `POST http://127.0.0.1:7800/a2a/rpc`
- QQ OneBot v11 webhook: `POST http://127.0.0.1:7800/api/qq/onebot`

QQ integration is designed for OneBot-compatible gateways such as NapCat or Lagrange. Configure the gateway to post message events to `/api/qq/onebot`, then set these optional environment variables before starting the daemon:

```powershell
$env:MOZILCODE_QQ_ONEBOT_API_URL="http://127.0.0.1:3000"
$env:MOZILCODE_QQ_ONEBOT_ACCESS_TOKEN="<optional-token>"
$env:MOZILCODE_QQ_ONEBOT_SECRET="<optional-secret>"
$env:MOZILCODE_QQ_COMMAND_PREFIX="/mew"
uv run mozilcode-daemon
```

Private chats can send either `/mew <prompt>` or plain text. Group chats require the command prefix by default.

Official QQ Bot Gateway is also supported. Set `MOZILCODE_QQ_OFFICIAL_ENABLED=1`, `MOZILCODE_QQ_OFFICIAL_APP_ID`, and `MOZILCODE_QQ_OFFICIAL_APP_SECRET`, then start the daemon. The adapter subscribes to `GROUP_AND_C2C_EVENT` by default and replies to C2C messages plus group `@bot` messages through the official passive reply API. Use `scripts/start-qq-official-bot.ps1` from the workspace root for the local Windows setup.
