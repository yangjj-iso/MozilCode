"""/plan 命令：进入/退出 Plan 模式相关操作。"""

from __future__ import annotations

from mozilcode.commands.registry import Command, CommandContext, CommandType


async def handle_plan(ctx: CommandContext) -> None:
    ctx.ui.set_plan_mode(True)
    ctx.ui.add_system_message("已切换到 Plan 模式 — 只读，禁止写入和命令执行")
    if ctx.args:
        ctx.ui.send_user_message(ctx.args)


PLAN_COMMAND = Command(
    name="plan",
    aliases=["p"],
    description="切换到 Plan 模式",
    usage="/plan [任务描述]",
    type=CommandType.LOCAL_UI,
    handler=handle_plan,
)

