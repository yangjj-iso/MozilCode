"""权限预检核心 PermissionChecker。

分层决策 allow / deny / ask。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mozilcode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from mozilcode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from mozilcode.permissions.rules import (
    RuleEngine,
)
from mozilcode.permissions.sandbox import PathSandbox
from mozilcode.permissions.tool_fields import extract_content, extract_sandbox_path
from mozilcode.tools.base import Tool

_PLAN_MODE_ALLOWED_TOOLS = frozenset({"Agent", "ToolSearch", "AskUserQuestion", "ExitPlanMode"})


@dataclass
class Decision:
    effect: DecisionEffect
    reason: str


class PermissionChecker:
    def __init__(
        self,
        detector: DangerousCommandDetector,
        sandbox: PathSandbox,
        rule_engine: RuleEngine,
        mode: PermissionMode = PermissionMode.DEFAULT,
    ) -> None:
        self.detector = detector
        self.sandbox = sandbox
        self.rule_engine = rule_engine
        self.mode = mode
        self.plan_file_path: str = ""

    def check(self, tool: Tool, arguments: dict[str, Any]) -> Decision:
        content = extract_content(tool.name, arguments)

        # Layer 0: Plan 模式例外放行
        decision = self._check_plan_mode(tool, content)
        if decision is not None:
            return decision

        decision = self._check_command_safety(tool, content)
        if decision is not None:
            return decision

        # Layer 2: 路径沙箱（仅实际触达文件系统的工具）
        decision = self._check_path_sandbox(tool, arguments)
        if decision is not None:
            return decision

        # Layer 3: 规则引擎匹配
        decision = self._check_rules(tool, content)
        if decision is not None:
            return decision

        # Layer 4: 权限模式兜底判定
        decision = self._check_mode_fallback(tool)
        if decision is not None:
            return decision

        # Layer 5: 触发人工确认（HITL）
        return Decision(effect="ask", reason="需要用户确认")

    def _check_plan_mode(self, tool: Tool, content: str) -> Decision | None:
        if self.mode != PermissionMode.PLAN:
            return None
        if tool.name in _PLAN_MODE_ALLOWED_TOOLS:
            return Decision(effect="allow", reason="Plan mode: allowed tool")
        if tool.name in ("WriteFile", "EditFile") and content:
            if self._is_plan_file(content):
                ok, reason = self.sandbox.check(content)
                if not ok:
                    return Decision(
                        effect="deny",
                        reason=f"路径沙箱拦截: {reason}",
                    )
                return Decision(effect="allow", reason="Plan mode: plan file write")
        return None

    def _check_command_safety(self, tool: Tool, content: str) -> Decision | None:
        if tool.category != "command":
            return None
        # Layer 1: 安全的只读命令（自动放行）
        if is_safe_command(content or ""):
            return Decision(effect="allow", reason="Safe read-only command")

        # Layer 1b: 危险命令黑名单（仅 Bash）
        hit, reason = self.detector.detect(content)
        if hit:
            return Decision(effect="deny", reason=f"危险命令拦截: {reason}")
        return None

    def _check_path_sandbox(
        self,
        tool: Tool,
        arguments: dict[str, Any],
    ) -> Decision | None:
        if tool.category not in ("read", "write"):
            return None
        target_path = extract_sandbox_path(tool.name, arguments)
        if target_path is None:
            return None
        if not target_path.strip():
            return Decision(effect="deny", reason="路径沙箱拦截: 缺少路径参数")
        ok, reason = self.sandbox.check(target_path)
        if not ok:
            return Decision(effect="deny", reason=f"路径沙箱拦截: {reason}")
        return None

    def _check_rules(self, tool: Tool, content: str) -> Decision | None:
        rule_result = self.rule_engine.evaluate(tool.name, content)
        if rule_result == "allow":
            return Decision(effect="allow", reason="权限规则放行")
        if rule_result == "deny":
            return Decision(effect="deny", reason="权限规则拒绝")
        return None

    def _check_mode_fallback(self, tool: Tool) -> Decision | None:
        effect = mode_decide(self.mode, tool.category)
        if effect == "allow":
            return Decision(effect="allow", reason=f"权限模式 {self.mode.value} 放行")
        if effect == "deny":
            return Decision(effect="deny", reason=f"权限模式 {self.mode.value} 拒绝")
        return None

    def _is_plan_file(self, target_path: str) -> bool:
        if not target_path:
            return False

        target = self._normalize_plan_candidate(target_path)
        if target is None:
            return False

        if self.plan_file_path:
            plan = self._normalize_plan_candidate(self.plan_file_path)
            if plan is not None and target == plan:
                return True

        plans_dir = (
            self.sandbox.project_root / ".mozilcode" / "plans"
        ).resolve(strict=False)
        try:
            target.relative_to(plans_dir)
            return True
        except ValueError:
            return False

    def _normalize_plan_candidate(self, path: str) -> Path | None:
        try:
            candidate = Path(path).expanduser()
            if not candidate.is_absolute():
                candidate = self.sandbox.project_root / candidate
            return candidate.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return None
