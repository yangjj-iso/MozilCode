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

## A2A and official bots

The daemon also exposes a non-streaming A2A bridge:

- Agent card: `GET http://127.0.0.1:7800/.well-known/agent-card.json`
- JSON-RPC: `POST http://127.0.0.1:7800/a2a/rpc`

Official bot integrations are configured in the GUI under `个人中心 -> QQ Bot` or `个人中心 -> Telegram Bot`. Secrets are stored locally in `~/.mozilcode/gui_settings.json` and are not returned by status APIs.

Official QQ Bot Gateway:

- Status: `GET http://127.0.0.1:7800/api/settings/qqbot`
- Environment fallback: `MOZILCODE_QQ_OFFICIAL_ENABLED=1`, `MOZILCODE_QQ_OFFICIAL_APP_ID`, `MOZILCODE_QQ_OFFICIAL_APP_SECRET`
- Windows helper: `scripts/start-qq-official-bot.ps1`

Official Telegram Bot API:

- Status: `GET http://127.0.0.1:7800/api/settings/telegrambot`
- Environment fallback: `MOZILCODE_TELEGRAM_ENABLED=1`, `MOZILCODE_TELEGRAM_BOT_TOKEN`
- Windows helper: `scripts/start-telegram-bot.ps1`

Private chats can send either `/mew <prompt>` or plain text. Group chats require the configured command prefix by default.

## Memory plugins

Long-term memory is routed through `MemoryHub`, with the legacy Markdown memory kept as the default provider. Custom memory systems can be added with `memory.providers` in `config.yaml` using `type: python`, `module`, and `class`.

See `mozilcode/docs/memory-plugins.md` for the provider protocol, configuration examples, and guidance for adapting external memory projects such as Tencent agent-memory.
