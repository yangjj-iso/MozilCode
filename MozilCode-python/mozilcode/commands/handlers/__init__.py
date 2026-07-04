from __future__ import annotations

from mozilcode.commands.handlers.clear import CLEAR_COMMAND
from mozilcode.commands.handlers.compact import COMPACT_COMMAND
from mozilcode.commands.handlers.do import DO_COMMAND
from mozilcode.commands.handlers.help import HELP_COMMAND
from mozilcode.commands.handlers.mcp import MCP_COMMAND
from mozilcode.commands.handlers.memory import MEMORY_COMMAND
from mozilcode.commands.handlers.permission import PERMISSION_COMMAND
from mozilcode.commands.handlers.plan import PLAN_COMMAND
from mozilcode.commands.handlers.session import SESSION_COMMAND
from mozilcode.commands.handlers.skill import SKILL_COMMAND
from mozilcode.commands.handlers.rewind import REWIND_COMMAND
from mozilcode.commands.handlers.status import STATUS_COMMAND
from mozilcode.commands.registry import CommandRegistry


ALL_COMMANDS = [
    HELP_COMMAND,
    COMPACT_COMMAND,
    CLEAR_COMMAND,
    PLAN_COMMAND,
    DO_COMMAND,
    SESSION_COMMAND,
    MCP_COMMAND,
    MEMORY_COMMAND,
    PERMISSION_COMMAND,
    REWIND_COMMAND,
    STATUS_COMMAND,
    SKILL_COMMAND,
]


def register_all_commands(registry: CommandRegistry) -> None:
    for cmd in ALL_COMMANDS:
        registry.register_sync(cmd)
