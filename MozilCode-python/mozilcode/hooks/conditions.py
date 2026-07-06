from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mozilcode.hooks.models import HookContext


@dataclass
class Condition:
    field: str
    operator: str
    value: str


    def evaluate(self, ctx: HookContext) -> bool:
        field_value = ctx.get_field(self.field)
        if self.operator == "==":
            return field_value == self.value
        if self.operator == "!=":
            return field_value != self.value
        if self.operator == "=~":
            pattern = self.value
            if pattern.startswith("/") and pattern.endswith("/"):
                pattern = pattern[1:-1]
            try:
                return bool(re.search(pattern, field_value))
            except re.error:
                return False
        if self.operator == "~=":
            return fnmatch.fnmatch(field_value, self.value)
        return False


@dataclass
class ConditionGroup:
    conditions: list[Condition] = field(default_factory=list)
    logic: str = "and"


    def evaluate(self, ctx: HookContext) -> bool:
        if not self.conditions:
            return True
        if self.logic == "and":
            return all(c.evaluate(ctx) for c in self.conditions)
        return any(c.evaluate(ctx) for c in self.conditions)


class ConditionParseError(Exception):
    pass


_OPERATORS = ("==", "!=", "=~", "~=")
_ARG_FIELD_RE = re.compile(r"^args\.[A-Za-z_][A-Za-z0-9_.-]*$")


def _validate_field(field: str, expr: str) -> None:
    if not field:
        raise ConditionParseError(f"Missing field in condition: '{expr}'")
    if field in {"tool", "event"}:
        return
    if _ARG_FIELD_RE.fullmatch(field):
        return
    raise ConditionParseError(
        f"Invalid field '{field}' in condition: '{expr}'. "
        "Expected 'tool', 'event', or 'args.<name>'."
    )


def _parse_value(raw_value: str, expr: str) -> str:
    if not raw_value:
        raise ConditionParseError(f"Missing value in condition: '{expr}'")
    if raw_value.startswith('"') and raw_value.endswith('"'):
        return raw_value[1:-1]
    return raw_value


def _parse_single(expr: str) -> Condition:
    expr = expr.strip()
    if not expr:
        raise ConditionParseError("Empty condition segment")
    found = [
        (idx, op)
        for op in _OPERATORS
        if (idx := expr.find(op)) != -1
    ]
    if found:
        idx, op = min(found, key=lambda match: match[0])
        field_part = expr[:idx].strip()
        value_part = expr[idx + len(op):].strip()
        _validate_field(field_part, expr)
        return Condition(
            field=field_part,
            operator=op,
            value=_parse_value(value_part, expr),
        )
    raise ConditionParseError(f"No valid operator found in condition: '{expr}'")


def parse_condition(expr: str) -> ConditionGroup | None:
    if not expr or not expr.strip():
        return None

    expr = expr.strip()
    has_and = "&&" in expr
    has_or = "||" in expr

    if has_and and has_or:
        raise ConditionParseError(
            "Cannot mix '&&' and '||' in a single condition expression. "
            "Split into separate hooks instead."
        )

    if has_and:
        parts = expr.split("&&")
        logic = "and"
    elif has_or:
        parts = expr.split("||")
        logic = "or"
    else:
        parts = [expr]
        logic = "and"

    conditions = [_parse_single(p) for p in parts]
    return ConditionGroup(conditions=conditions, logic=logic)
