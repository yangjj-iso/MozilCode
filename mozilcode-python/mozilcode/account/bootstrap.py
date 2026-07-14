"""TUI/CLI 首次启动时的账号登录引导。"""

from __future__ import annotations

import getpass
import sys

from mozilcode.account import (
    AccountClientError,
    DEFAULT_BASE_URL,
    get_status,
    list_catalog,
    select_model,
    sign_in,
)


def interactive_sign_in(stream_in=None, stream_out=None) -> bool:
    """在终端引导登录/注册。成功返回 True。"""
    stdin = stream_in or sys.stdin
    stdout = stream_out or sys.stdout

    def write(msg: str) -> None:
        print(msg, file=stdout)

    def read(prompt: str) -> str:
        write(prompt)
        return stdin.readline().strip()

    write("未找到本地模型配置。可登录 MozilCode Cloud 使用官方模型。")
    write("（也可先编辑 ~/.mozilcode/config.yaml 配置本地 Provider）")
    write("")
    base = read(f"Cloud URL [{DEFAULT_BASE_URL}]: ") or DEFAULT_BASE_URL
    email = read("Email: ")
    if not email:
        write("已取消。")
        return False
    if stdin is sys.stdin and stdout is sys.stdout and sys.stdin.isatty():
        password = getpass.getpass("Password: ")
    else:
        password = read("Password: ")
    if not password:
        write("已取消。")
        return False
    mode = (read("Register new account? [y/N]: ") or "n").lower()
    register = mode in {"y", "yes"}
    try:
        session = sign_in(
            email=email,
            password=password,
            base_url=base,
            register=register,
        )
        models = list_catalog()
    except AccountClientError as exc:
        write(f"登录失败: {exc}")
        return False

    if not models:
        write(
            f"已登录 {session.email}，但云端暂无可用模型。\n"
            "请管理员在 /ops 启用模型后再试。"
        )
        return False

    write("可用模型:")
    for i, m in enumerate(models, start=1):
        write(f"  {i}. {m.name}  ({m.display_name})")
    choice = read(f"选择模型 [1-{len(models)}] (默认 1): ") or "1"
    try:
        idx = int(choice) - 1
    except ValueError:
        idx = 0
    if idx < 0 or idx >= len(models):
        idx = 0
    selected = select_model(models[idx].name)
    write(f"已登录 {selected.email}，模型 {selected.selected_model}")
    return True


def ensure_runtime_config():
    """加载配置；失败时尝试账号引导后重载。"""
    from mozilcode.config import ConfigError, load_config

    try:
        return load_config()
    except ConfigError:
        status = get_status()
        if status.logged_in:
            raise
        if not sys.stdin.isatty():
            raise
        if not interactive_sign_in():
            raise
        return load_config()