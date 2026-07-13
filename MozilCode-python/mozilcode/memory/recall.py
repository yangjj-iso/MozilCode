from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 最多扫描的记忆文件数量上限
MAX_MEMORY_FILES = 200
# 读取 frontmatter 时只读前 N 行（避免读取整个大文件）
FRONTMATTER_MAX_LINES = 30
# 入口文件名（扫描时跳过，不作为记忆文件）
ENTRYPOINT_NAME = "MEMORY.md"
# 有效的记忆类型集合（对应 frontmatter 中的 type 字段）
VALID_TYPES = {"user", "feedback", "project", "reference"}

# frontmatter 正则：匹配 --- 包裹的 YAML 头部
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 选择器 LLM 的 system prompt：让 LLM 从清单中选出最多 5 个相关记忆文件
SELECTOR_SYSTEM_PROMPT = (
    "You are selecting memories that will be useful to MozilCode as it processes "
    "a user's query. You will be given the user's query and a list of available "
    "memory files with their filenames and descriptions.\n\n"
    "Return a list of filenames for the memories that will clearly be useful to "
    "MozilCode as it processes the user's query (up to 5). Only include memories "
    "that you are certain will be helpful based on their name and description.\n"
    "- If you are unsure if a memory will be useful in processing the user's "
    "query, then do not include it in your list. Be selective and discerning.\n"
    "- If there are no memories in the list that would clearly be useful, feel "
    "free to return an empty list.\n"
    "- If a list of recently-used tools is provided, do not select memories "
    "that are usage reference or API documentation for those tools (MozilCode is "
    "already exercising them). DO still select memories containing warnings, "
    "gotchas, or known issues about those tools — active use is exactly when "
    "those matter.\n\n"
    'Respond with valid JSON only, no markdown, in this exact shape: '
    '{"selected_memories": ["filename1.md", "filename2.md"]}'
)

# 选择器函数类型：接收 system_prompt 和 user_message，返回 LLM 的原始响应文本
SelectorFn = Callable[[str, str], Awaitable[str]]


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class MemoryHeader:
    """记忆文件的元信息（从 frontmatter 和文件系统中提取）。"""
    filename: str      # 相对于 memory_dir 的路径
    file_path: str     # 绝对路径
    scope: str         # 作用域："user" 或 "project"
    mtime_ms: int      # 修改时间（毫秒时间戳）
    description: str   # frontmatter 中的描述；无则为 ""
    type: str          # frontmatter 中的类型；无法识别则为 ""


@dataclass
class RelevantMemory:
    """被选择器选中的记忆文件（路径 + 修改时间）。"""
    path: str
    mtime_ms: int


# ---------------------------------------------------------------------------
# 记忆时效性辅助函数
# ---------------------------------------------------------------------------

def memory_age_days(mtime_ms: int) -> int:
    """返回记忆文件的年龄（天数，向下取整）。今天为 0，昨天为 1。"""
    d = (int(time.time() * 1000) - mtime_ms) // 86_400_000
    return max(d, 0)


def memory_age(mtime_ms: int) -> str:
    """返回人类可读的年龄描述：'today' / 'yesterday' / 'N days ago'。"""
    d = memory_age_days(mtime_ms)
    if d == 0:
        return "today"
    if d == 1:
        return "yesterday"
    return f"{d} days ago"


def memory_freshness_text(mtime_ms: int) -> str:
    """为超过 1 天的记忆生成过期警告文本。新记忆返回空字符串。

    提醒 LLM：记忆是历史快照而非实时状态，引用前需核实当前代码。
    """
    d = memory_age_days(mtime_ms)
    if d <= 1:
        return ""
    return (
        f"This memory is {d} days old. "
        "Memories are point-in-time observations, not live state — "
        "claims about code behavior or file:line citations may be outdated. "
        "Verify against current code before asserting as fact."
    )


# ---------------------------------------------------------------------------
# Frontmatter 解析
# ---------------------------------------------------------------------------

def parse_frontmatter(content: str) -> dict[str, str]:
    """从 YAML 风格的 frontmatter 中提取 name / description / type 三个字段。

    只读取这三个已知字段，其余内容忽略。无 frontmatter 的文件返回空值。
    采用简化解析（不依赖 PyYAML），逐行找冒号分隔。
    """
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {"name": "", "description": "", "type": ""}

    block = m.group(1)
    result: dict[str, str] = {"name": "", "description": "", "type": ""}
    for line in block.split("\n"):
        colon = line.find(":")
        if colon < 0:
            continue
        key = line[:colon].strip()
        val = line[colon + 1 :].strip()
        # Strip quotes.
        if len(val) >= 2 and (
            (val.startswith('"') and val.endswith('"'))
            or (val.startswith("'") and val.endswith("'"))
        ):
            val = val[1:-1]
        if key == "name":
            result["name"] = val
        elif key == "description":
            result["description"] = val
        elif key == "type":
            if val in VALID_TYPES:
                result["type"] = val
    return result


# ---------------------------------------------------------------------------
# 文件扫描
# ---------------------------------------------------------------------------

def scan_memory_files(memory_dir: Path, scope: str) -> list[MemoryHeader]:
    """递归扫描 memory_dir 下的 .md 文件（排除 MEMORY.md），
    读取每个文件的 frontmatter，返回按修改时间降序排列的头部列表，
    最多 MAX_MEMORY_FILES 个。
    """
    if not memory_dir.is_dir():
        return []

    md_files: list[Path] = []
    try:
        for fp in memory_dir.rglob("*.md"):
            if fp.is_file() and fp.name != ENTRYPOINT_NAME:
                md_files.append(fp)
    except OSError:
        return []

    results: list[MemoryHeader] = []
    for fp in md_files:
        hdr = _read_memory_header(fp, memory_dir, scope)
        if hdr is not None:
            results.append(hdr)

    # Sort newest-first.
    results.sort(key=lambda h: h.mtime_ms, reverse=True)
    if len(results) > MAX_MEMORY_FILES:
        results = results[:MAX_MEMORY_FILES]
    return results


def _read_memory_header(
    file_path: Path, memory_dir: Path, scope: str
) -> MemoryHeader | None:
    """读取单个记忆文件的头部信息（修改时间 + frontmatter）。
    只读前 FRONTMATTER_MAX_LINES 行以避免读取大文件。
    """
    try:
        mtime_ms = int(file_path.stat().st_mtime * 1000)
    except OSError:
        return None

    # Read first FRONTMATTER_MAX_LINES for frontmatter parsing.
    try:
        lines: list[str] = []
        with file_path.open(encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= FRONTMATTER_MAX_LINES:
                    break
                lines.append(line)
        content = "".join(lines)
    except OSError:
        return None

    fm = parse_frontmatter(content)
    try:
        rel = str(file_path.relative_to(memory_dir))
    except ValueError:
        rel = file_path.name

    return MemoryHeader(
        filename=rel,
        file_path=str(file_path.resolve()),
        scope=scope,
        mtime_ms=mtime_ms,
        description=fm["description"],
        type=fm["type"],
    )


# ---------------------------------------------------------------------------
# 清单格式化
# ---------------------------------------------------------------------------

def format_memory_manifest(memories: list[MemoryHeader]) -> str:
    """将记忆头部列表格式化为文本清单，供选择器 LLM 阅读。

    每行包含：scope 标签 / type 标签 / 文件路径 / 时间戳 / 描述。
    """
    if not memories:
        return ""
    lines: list[str] = []
    for m in memories:
        scope_tag = f"[{m.scope}-scope] " if m.scope else ""
        type_tag = f"[{m.type}] " if m.type else ""
        ts = datetime.fromtimestamp(
            m.mtime_ms / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.") + f"{m.mtime_ms % 1000:03d}Z"
        path = m.file_path if m.file_path else m.filename
        if m.description:
            lines.append(f"- {scope_tag}{type_tag}{path} ({ts}): {m.description}")
        else:
            lines.append(f"- {scope_tag}{type_tag}{path} ({ts})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 语义召回
# ---------------------------------------------------------------------------

async def find_relevant_memories(
    query: str,
    user_mem_dir: Path | None,
    project_mem_dir: Path | None,
    recent_tools: list[str] | None,
    already_surfaced: set[str] | None,
    selector: SelectorFn,
) -> list[RelevantMemory]:
    """语义召回：扫描两个记忆目录 → 过滤已展示的 → 让 LLM 选择器选出最多 5 个相关文件。

    流程：
    1. 扫描用户级和项目级记忆目录
    2. 过滤掉已经展示过的文件（避免重复）
    3. 格式化清单 → 调用选择器 LLM → 解析 JSON 响应
    4. 返回选中文件的路径 + 修改时间

    选择器失败时静默返回空列表（记忆召回是 best-effort，不阻断主对话）。
    """
    all_headers: list[MemoryHeader] = []
    if user_mem_dir is not None:
        all_headers.extend(scan_memory_files(user_mem_dir, "user"))
    if project_mem_dir is not None:
        all_headers.extend(scan_memory_files(project_mem_dir, "project"))

    surfaced = already_surfaced or set()
    candidates = [m for m in all_headers if m.file_path not in surfaced]
    if not candidates:
        return []

    selected_filenames = await _select_relevant_memories(
        query, candidates, recent_tools, selector
    )

    # Build lookup from both file_path and filename to header.
    by_key: dict[str, MemoryHeader] = {}
    for m in candidates:
        by_key[m.file_path] = m
        by_key.setdefault(m.filename, m)

    result: list[RelevantMemory] = []
    for fn in selected_filenames:
        m = by_key.get(fn)
        if m is not None:
            result.append(RelevantMemory(path=m.file_path, mtime_ms=m.mtime_ms))
    return result


async def _select_relevant_memories(
    query: str,
    memories: list[MemoryHeader],
    recent_tools: list[str] | None,
    selector: SelectorFn,
) -> list[str]:
    """格式化清单 → 调用选择器 LLM → 解析 JSON → 返回合法文件名列表。"""
    valid_filenames = {m.filename for m in memories}

    manifest = format_memory_manifest(memories)

    tools_section = ""
    if recent_tools:
        tools_section = "\n\nRecently used tools: " + ", ".join(recent_tools)

    user_message = f"Query: {query}\n\nAvailable memories:\n{manifest}{tools_section}"

    try:
        raw = await selector(SELECTOR_SYSTEM_PROMPT, user_message)
    except Exception:
        return []

    clean = _extract_json_object(raw)
    if not clean:
        return []

    try:
        parsed = json.loads(clean)
        arr = parsed.get("selected_memories", [])
        if not isinstance(arr, list):
            return []
        return [f for f in arr if isinstance(f, str) and f in valid_filenames]
    except (json.JSONDecodeError, AttributeError):
        return []


def _extract_json_object(raw: str) -> str:
    """从 LLM 原始响应中提取第一个 {...} 子串。
    容忍 markdown 代码块或散文包裹的 JSON。
    """
    trimmed = raw.strip()
    if trimmed.startswith("{"):
        return trimmed
    start = trimmed.find("{")
    if start < 0:
        return ""
    end = trimmed.rfind("}")
    if end < start:
        return ""
    return trimmed[start : end + 1]


# ---------------------------------------------------------------------------
# 提醒渲染
# ---------------------------------------------------------------------------

def render_reminder(memories: list[RelevantMemory]) -> str:
    """读取每个选中记忆文件的完整内容，格式化为 system-reminder 文本。

    每个记忆块包含：文件名 / 保存时间 / 过期警告（如果有）/ 文件内容。
    最终作为 system-reminder 注入对话，让 LLM 参考历史记忆。
    """
    if not memories:
        return ""

    parts: list[str] = []
    parts.append("The following relevant memories from prior conversations may help:\n")
    for mem in memories:
        try:
            content = Path(mem.path).read_text(encoding="utf-8")
        except OSError:
            continue  # skip unreadable files
        basename = Path(mem.path).name
        parts.append(f"## Memory: {basename} (saved {memory_age(mem.mtime_ms)})\n")
        note = memory_freshness_text(mem.mtime_ms)
        if note:
            parts.append(note + "\n")
        parts.append(content + "\n\n---\n")
    return "\n".join(parts)
