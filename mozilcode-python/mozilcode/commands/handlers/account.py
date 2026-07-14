"""/account 命令：登录云端、查看目录、选择模型。"""

from __future__ import annotations

from mozilcode.account import (
    AccountClientError,
    get_status,
    list_catalog,
    select_model,
    sign_in,
    sign_out,
)
from mozilcode.commands.registry import Command, CommandContext, CommandType


def _usage() -> str:
    return (
        "用法:\n"
        "  /account status\n"
        "  /account signin <email> <password> [base_url]\n"
        "  /account register <email> <password> [base_url]\n"
        "  /account models\n"
        "  /account use <model>\n"
        "  /account signout\n"
        "说明: 登录后本地通过 gateway 推理，密钥留在云端。"
    )


async def handle_account(ctx: CommandContext) -> None:
    parts = (ctx.args or "").split()
    if not parts:
        status = get_status()
        if status.logged_in:
            lines = [
                "账号状态",
                "────────",
                f"邮箱: {status.email or '—'}",
                f"角色: {status.role or '—'}",
                f"云端: {status.base_url}",
                f"已选模型: {status.selected_model or '（未选）'}",
                f"会话文件: {status.session_path}",
                "",
                "可用子命令: models | use <model> | signout",
            ]
            ctx.ui.add_system_message("\n".join(lines))
        else:
            ctx.ui.add_system_message(_usage())
        return

    action = parts[0].lower()
    try:
        if action in {"status", "whoami"}:
            status = get_status()
            if not status.logged_in:
                ctx.ui.add_system_message("未登录。使用 /account signin <email> <password>")
                return
            ctx.ui.add_system_message(
                "\n".join(
                    [
                        f"已登录: {status.email}",
                        f"角色: {status.role}",
                        f"云端: {status.base_url}",
                        f"模型: {status.selected_model or '（未选）'}",
                    ]
                )
            )
            return

        if action in {"signin", "login", "register"}:
            if len(parts) < 3:
                ctx.ui.add_system_message("用法: /account signin <email> <password> [base_url]")
                return
            email, password = parts[1], parts[2]
            base_url = parts[3] if len(parts) >= 4 else None
            session = sign_in(
                email=email,
                password=password,
                base_url=base_url,
                register=action == "register",
            )
            models = []
            try:
                models = list_catalog()
            except AccountClientError:
                pass
            selected = session.selected_model
            if models and not selected:
                session = select_model(models[0].name)
                selected = session.selected_model
            ctx.ui.add_system_message(
                f"已{'注册并' if action == 'register' else ''}登录 {session.email}\n"
                f"云端: {session.base_url}\n"
                f"当前模型: {selected or '请用 /account use <model>'}\n"
                "提示: 新会话会使用账号模型；已打开会话不受影响。"
            )
            return

        if action in {"models", "ls", "list"}:
            models = list_catalog()
            status = get_status()
            if not models:
                ctx.ui.add_system_message("云端暂无可用模型（管理员需在 /ops 启用）")
                return
            lines = ["云端模型目录", "────────────"]
            for m in models:
                mark = "*" if m.name == status.selected_model else " "
                lines.append(f"{mark} {m.name}  ({m.display_name})")
            lines.append("")
            lines.append("选择: /account use <model>")
            ctx.ui.add_system_message("\n".join(lines))
            return

        if action in {"use", "select", "model"}:
            if len(parts) < 2:
                ctx.ui.add_system_message("用法: /account use <model>")
                return
            model = parts[1]
            session = select_model(model)
            ctx.ui.add_system_message(
                f"已选择模型: {session.selected_model}\n"
                "新会话将走云端 gateway。"
            )
            return

        if action in {"signout", "logout"}:
            sign_out()
            ctx.ui.add_system_message("已退出云端账号。")
            return

        ctx.ui.add_system_message(_usage())
    except AccountClientError as exc:
        ctx.ui.add_system_message(f"账号错误: {exc}")


ACCOUNT_COMMAND = Command(
    name="account",
    aliases=["acc"],
    description="登录/管理 MozilCode Cloud 账号与模型",
    usage="/account [status|signin|register|models|use|signout]",
    type=CommandType.LOCAL,
    handler=handle_account,
)