from __future__ import annotations

import re
import shlex

_RM_ROOT_REASON = "递归强制删除根目录"

_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/\s*$"), _RM_ROOT_REASON),
    (re.compile(r"mkfs\."), "格式化磁盘"),
    (re.compile(r"dd\s+if=.*of=/dev/"), "直接写磁盘设备"),
    (re.compile(r"chmod\s+-R\s+777\s+/"), "递归修改根目录权限"),
    (re.compile(r":\(\)\{\s*:\|:&\s*\};:"), "fork bomb"),
    (re.compile(r"curl\s+.*\|\s*(ba)?sh"), "管道执行远程脚本"),
    (re.compile(r"wget\s+.*\|\s*(ba)?sh"), "管道执行远程脚本"),
    (re.compile(r">\s*/dev/sd"), "覆盖磁盘设备"),
]


_SAFE_EXACT_COMMANDS = frozenset({
    "pwd", "whoami", "hostname", "date", "cal", "uptime", "env", "printenv",
    "true", "false", "go version", "node -v", "npm -v", "python --version",
    "cargo --version", "rustc --version", "java -version", "java --version",
})

_SAFE_PREFIX_COMMANDS = frozenset({
    "ls", "dir", "echo", "cat", "head", "tail", "wc",
    "which", "whereis", "uname", "df", "du", "free",
    "file", "stat", "readlink", "realpath", "basename", "dirname",
    "uniq", "tr", "cut", "grep", "egrep", "fgrep", "diff", "comm", "test",
    "git status", "git log", "git diff", "git show", "git branch",
    "git tag", "git remote", "git rev-parse", "git ls-files",
    "git blame", "git stash list", "pip list",
})


def _tokenize_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _short_rm_flags(flag: str) -> tuple[bool, bool]:
    if not flag.startswith("-") or flag.startswith("--"):
        return False, False
    chars = flag[1:].lower()
    return "r" in chars, "f" in chars


def _detect_rm_root(command: str) -> bool:
    tokens = _tokenize_command(command)
    for index, token in enumerate(tokens):
        if token != "rm":
            continue

        recursive = False
        force = False
        for arg in tokens[index + 1:]:
            if arg in {";", "&&", "||", "|"}:
                break
            short_recursive, short_force = _short_rm_flags(arg)
            if arg == "--recursive" or short_recursive:
                recursive = True
            if arg == "--force" or short_force:
                force = True
            if (
                arg in {"--recursive", "--force", "--no-preserve-root"}
                or short_recursive
                or short_force
            ):
                continue
            if arg in {"/", "/*"}:
                return recursive and force
            if not arg.startswith("-"):
                break
    return False


def is_safe_command(command: str) -> bool:
    trimmed = command.strip()
    if not trimmed:
        return False
    for ch in ("|", ";", "&&", "||", ">", "<", "$(", "`", "\n", "\r"):
        if ch in trimmed:
            return False
    if trimmed in _SAFE_EXACT_COMMANDS:
        return True
    for safe in _SAFE_PREFIX_COMMANDS:
        if trimmed == safe or trimmed.startswith(safe + " "):
            return True
    return False


class DangerousCommandDetector:


    def __init__(self, extra_patterns: list[tuple[str, str]] | None = None) -> None:
        self._patterns = list(_DANGEROUS_PATTERNS)
        if extra_patterns:
            for regex_str, reason in extra_patterns:
                self._patterns.append((re.compile(regex_str), reason))


    def detect(self, command: str) -> tuple[bool, str]:
        if _detect_rm_root(command):
            return True, _RM_ROOT_REASON
        for pattern, reason in self._patterns:
            if pattern.search(command):
                return True, reason
        return False, ""
