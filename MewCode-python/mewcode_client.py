"""MewCode Daemon 客户端 — 一个交互式终端客户端，连接本地 daemon。

用法:
    .venv\\Scripts\\python.exe mewcode_client.py

功能:
    - 输入消息，Agent 流式回复
    - Agent 调工具时显示工具名和结果
    - Agent 提问时在终端交互回答
    - 权限请求时在终端批准/拒绝
    - 输入 /exit 退出, /new 新建会话
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx
import websockets

DAEMON_URL = "http://127.0.0.1:7800"
WS_URL = "ws://127.0.0.1:7800"


class Colors:
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def c(text: str, color: str) -> str:
    return f"{color}{text}{Colors.RESET}"


class MewCodeClient:
    def __init__(self) -> None:
        self.session_id: str | None = None
        self.http = httpx.AsyncClient(timeout=30)
        self._streaming_text = False

    async def init(self) -> None:
        r = await self.http.get(f"{DAEMON_URL}/api/health")
        data = r.json()
        if data.get("status") != "ok":
            print(c("Daemon 未运行！请先启动: python -m mewcode.daemon", Colors.RED))
            sys.exit(1)
        print(c("✓ 已连接到 MewCode Daemon", Colors.GREEN))

        r = await self.http.post(f"{DAEMON_URL}/api/session", json={})
        self.session_id = r.json()["session_id"]
        print(c(f"✓ 会话已创建: {self.session_id}", Colors.GREEN))
        print(c("输入消息与 Agent 对话，输入 /exit 退出，/new 新建会话\n", Colors.DIM))

    async def send_message(self, prompt: str) -> None:
        r = await self.http.post(
            f"{DAEMON_URL}/api/task",
            json={"session_id": self.session_id, "prompt": prompt},
        )
        if r.status_code != 200:
            print(c(f"发送失败: {r.text}", Colors.RED))
            return
        task_id = r.json().get("task_id", "")
        await self._stream_events(task_id)

    async def _stream_events(self, task_id: str) -> None:
        """连接 WebSocket，流式接收事件直到完成。"""
        uri = f"{WS_URL}/api/stream/{self.session_id}"
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=120)
                    except asyncio.TimeoutError:
                        print(c("\n(超时，未收到事件)", Colors.DIM))
                        break

                    if msg is None:
                        break

                    data = json.loads(msg)
                    event_type = data.get("type", "")
                    d = data.get("data", {})

                    if event_type == "StreamText":
                        text = d.get("text", "")
                        if not self._streaming_text:
                            self._streaming_text = True
                        print(text, end="", flush=True)

                    elif event_type == "ThinkingText":
                        pass  # 静默处理 thinking

                    elif event_type == "ToolUseEvent":
                        if self._streaming_text:
                            print()  # 换行
                            self._streaming_text = False
                        tool = d.get("tool_name", "?")
                        args = d.get("arguments", {})
                        # 简短显示参数
                        arg_preview = self._format_tool_args(tool, args)
                        print(c(f"  → {tool}", Colors.CYAN), end="")
                        if arg_preview:
                            print(c(f"  {arg_preview}", Colors.DIM), end="")
                        print()

                    elif event_type == "ToolResultEvent":
                        output = d.get("output", "")
                        is_error = d.get("is_error", False)
                        elapsed = d.get("elapsed", 0)
                        preview = output[:120].replace("\n", " ")
                        if len(output) > 120:
                            preview += "..."
                        color = Colors.RED if is_error else Colors.GREEN
                        print(c(f"  ← {preview}", color), end="")
                        print(c(f"  ({elapsed:.1f}s)", Colors.DIM))

                    elif event_type == "PermissionRequest":
                        if self._streaming_text:
                            print()
                            self._streaming_text = False
                        desc = d.get("description", "")
                        req_id = d.get("request_id", "")
                        print(c(f"\n⚠ 权限请求: {desc}", Colors.YELLOW))
                        response = await self._ask_input("  批准? (y/n/a=always): ")
                        resp = "deny"
                        if response.strip().lower() in ("y", "yes"):
                            resp = "allow"
                        elif response.strip().lower() in ("a", "always"):
                            resp = "allow_always"
                        await self.http.post(
                            f"{DAEMON_URL}/api/permission/{self.session_id}",
                            json={"request_id": req_id, "response": resp},
                        )

                    elif event_type == "AskUserRequest":
                        if self._streaming_text:
                            print()
                            self._streaming_text = False
                        questions = d.get("questions", [])
                        req_id = d.get("request_id", "")
                        answers: dict[str, str] = {}
                        for q in questions:
                            qname = q.get("name", "q")
                            qmsg = q.get("message", "")
                            options = q.get("options", [])
                            if options:
                                print(c(f"\n? {qmsg}", Colors.YELLOW))
                                for i, opt in enumerate(options):
                                    print(c(f"  {i+1}. {opt}", Colors.DIM))
                                choice = await self._ask_input(f"  选择 (1-{len(options)}): ")
                                try:
                                    idx = int(choice.strip()) - 1
                                    if 0 <= idx < len(options):
                                        answers[qname] = options[idx]
                                    else:
                                        answers[qname] = choice.strip()
                                except ValueError:
                                    answers[qname] = choice.strip()
                            else:
                                answer = await self._ask_input(f"\n? {qmsg}: ")
                                answers[qname] = answer.strip()
                        await self.http.post(
                            f"{DAEMON_URL}/api/askuser/{self.session_id}",
                            json={"request_id": req_id, "answers": answers},
                        )

                    elif event_type == "UsageEvent":
                        inp = d.get("input_tokens", 0)
                        out = d.get("output_tokens", 0)
                        if self._streaming_text:
                            print()
                            self._streaming_text = False
                        print(c(f"  tokens: ↑{inp} ↓{out}", Colors.DIM))

                    elif event_type == "TurnComplete":
                        pass  # 静默

                    elif event_type == "LoopComplete":
                        if self._streaming_text:
                            print()
                            self._streaming_text = False
                        break

                    elif event_type == "ErrorEvent":
                        if self._streaming_text:
                            print()
                            self._streaming_text = False
                        print(c(f"  ✗ {d.get('message', '未知错误')}", Colors.RED))
                        break

                    elif event_type == "CompactNotification":
                        if self._streaming_text:
                            print()
                            self._streaming_text = False
                        print(c(f"  ↻ 上下文已压缩: {d.get('message', '')}", Colors.DIM))

                    elif event_type == "RetryEvent":
                        if self._streaming_text:
                            print()
                            self._streaming_text = False
                        print(c(f"  ↻ 重试: {d.get('reason', '')}", Colors.DIM))

                    elif event_type == "HookEvent":
                        hook_id = d.get("hook_id", "")
                        success = d.get("success", True)
                        color = Colors.GREEN if success else Colors.RED
                        print(c(f"  [hook:{hook_id}] {d.get('event', '')}", color))

        except Exception as e:
            if self._streaming_text:
                print()
                self._streaming_text = False
            print(c(f"  连接错误: {e}", Colors.RED))

    def _format_tool_args(self, tool: str, args: dict) -> str:
        """简短显示工具参数。"""
        if not args:
            return ""
        if tool in ("ReadFile", "WriteFile", "EditFile"):
            return args.get("file_path", "")
        if tool == "Bash":
            cmd = args.get("command", "")
            return cmd[:60] + ("..." if len(cmd) > 60 else "")
        if tool == "Glob":
            return args.get("pattern", "")
        if tool == "Grep":
            return args.get("pattern", "")
        if tool == "ToolSearch":
            return args.get("query", "")
        if tool == "Agent":
            return args.get("description", "")
        # 通用：显示前两个 key=value
        parts = [f"{k}={str(v)[:30]}" for k, v in list(args.items())[:2]]
        return ", ".join(parts)

    async def _ask_input(self, prompt: str) -> str:
        """在线程中同步获取用户输入（不阻塞事件循环）。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: input(c(prompt, Colors.BOLD)))

    async def new_session(self) -> None:
        r = await self.http.post(f"{DAEMON_URL}/api/session", json={})
        self.session_id = r.json()["session_id"]
        print(c(f"✓ 新会话: {self.session_id}", Colors.GREEN))

    async def close(self) -> None:
        if self.session_id:
            await self.http.delete(f"{DAEMON_URL}/api/session/{self.session_id}")
        await self.http.aclose()


async def main() -> None:
    client = MewCodeClient()
    await client.init()

    try:
        while True:
            try:
                prompt = input(c("\n> ", Colors.BOLD + Colors.CYAN))
            except (EOFError, KeyboardInterrupt):
                break

            prompt = prompt.strip()
            if not prompt:
                continue
            if prompt == "/exit":
                break
            if prompt == "/new":
                await client.new_session()
                continue

            await client.send_message(prompt)
    finally:
        await client.close()
        print(c("\n再见!", Colors.DIM))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
