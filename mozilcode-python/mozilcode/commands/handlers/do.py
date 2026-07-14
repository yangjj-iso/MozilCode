"""/do 命令：快捷执行用户指令类操作。"""

from __future__ import annotations

from mozilcode.commands.registry import Command, CommandContext, CommandType


async def handle_do(ctx: CommandContext) -> None:
    ctx.ui.set_plan_mode(False)
    ctx.ui.add_system_message("已切换到执行模式")
    if ctx.args:
        ctx.ui.send_user_message(ctx.args)


DO_COMMAND = Command(
    name="do",
    description="切换到执行模式",
    usage="/do [任务描述]",
    type=CommandType.LOCAL_UI,
    handler=handle_do,
)
