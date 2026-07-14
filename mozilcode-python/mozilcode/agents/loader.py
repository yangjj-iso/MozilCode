"""Agent 定义加载器。

从磁盘扫描并加载 AgentDef（frontmatter + 正文）。"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

from mozilcode.agents.parser import (
    AgentDef,
    AgentParseError,
    build_agent_def,
    parse_agent_file,
    parse_frontmatter,
)

log = logging.getLogger(__name__)

PROJECT_AGENTS_DIR = ".mozilcode/agents"
USER_AGENTS_DIR = "~/.mozilcode/agents"
PLUGIN_AGENTS_DIR = "agents"


class AgentLoader:


    def __init__(
        self,
        work_dir: str,
        enable_verification: bool = False,
        plugin_sources: list[str | Path] | None = None,
    ) -> None:
        self._work_dir = work_dir
        self._enable_verification = enable_verification
        self._agents: dict[str, AgentDef] = {}
        self._plugin_sources: list[Path] = []
        for source in plugin_sources or []:
            self.register_plugin_source(source)


    def _scan_directory(self, path: Path, source: str) -> list[AgentDef]:
        results: list[AgentDef] = []
        if not path.is_dir():
            return results

        for entry in sorted(path.iterdir()):
            if not entry.is_file() or entry.suffix != ".md":
                continue
            try:
                agent_def = parse_agent_file(entry)
                agent_def.source = source
                agent_def.file_path = entry
                results.append(agent_def)
            except AgentParseError as e:
                log.warning("Skipping agent file %s: %s", entry, e)
        return results

    def _scan_plugin_sources(self) -> list[AgentDef]:
        results: list[AgentDef] = []
        seen_paths: set[Path] = set()

        for source in self._plugin_sources:
            candidates = [source, source / PLUGIN_AGENTS_DIR]
            for candidate in candidates:
                if candidate in seen_paths:
                    continue
                seen_paths.add(candidate)
                results.extend(self._scan_directory(candidate, "plugin"))

        return results

    @staticmethod
    def _merge_missing(
        seen: dict[str, AgentDef],
        agents: list[AgentDef],
    ) -> None:
        for agent_def in agents:
            if agent_def.agent_type not in seen:
                seen[agent_def.agent_type] = agent_def


    def _load_builtins(self) -> list[AgentDef]:
        results: list[AgentDef] = []
        try:
            builtins_pkg = importlib.resources.files("mozilcode.agents.builtins")
        except (ModuleNotFoundError, TypeError):
            log.warning("Could not load built-in agents package")
            return results

        for item in builtins_pkg.iterdir():
            if not item.name.endswith(".md"):
                continue
            try:
                raw = item.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(raw)
                agent_def = build_agent_def(
                    meta,
                    body,
                    file_path=None,
                    source="builtin",
                )

                if (
                    agent_def.agent_type == "Verification"
                    and not self._enable_verification
                ):
                    continue

                results.append(agent_def)
            except (AgentParseError, Exception) as e:
                log.warning("Skipping built-in agent %s: %s", item.name, e)

        return results

    def load_all(self) -> dict[str, AgentDef]:
        seen: dict[str, AgentDef] = {}

        # 优先级 1：项目级（最高）
        project_path = Path(self._work_dir) / PROJECT_AGENTS_DIR
        self._merge_missing(seen, self._scan_directory(project_path, "project"))

        # 优先级 2：用户级
        user_path = Path(USER_AGENTS_DIR).expanduser()
        self._merge_missing(seen, self._scan_directory(user_path, "user"))

        # 优先级 3：内置
        self._merge_missing(seen, self._load_builtins())

        # 优先级 4：插件。插件可以新增 agent，但不能覆盖项目/用户/内置定义。
        self._merge_missing(seen, self._scan_plugin_sources())

        self._agents = seen
        return seen


    def get(self, agent_type: str) -> AgentDef | None:
        cached = self._agents.get(agent_type)
        if cached is None:
            return None

        # 从文件热重载
        if cached.file_path is not None and cached.file_path.exists():
            try:
                reloaded = parse_agent_file(cached.file_path)
                reloaded.source = cached.source
                self._agents[agent_type] = reloaded
                return reloaded
            except AgentParseError as e:
                log.warning(
                    "Hot reload failed for %s, using cached: %s",
                    agent_type,
                    e,
                )
        return cached


    def list_agents(self) -> list[tuple[str, str]]:
        return [
            (ad.agent_type, ad.when_to_use) for ad in self._agents.values()
        ]

    def register_plugin_source(self, path: str | Path) -> None:
        normalized = Path(path).expanduser()
        if normalized in self._plugin_sources:
            return
        self._plugin_sources.append(normalized)
        if self._agents:
            self.load_all()
