"""YAML frontmatter 解析。

从 Markdown/技能/Agent 定义等文本中拆出 --- YAML --- 元数据与正文。
"""

from __future__ import annotations

import yaml


class FrontmatterParseError(Exception):
    pass


def parse_yaml_frontmatter(raw: str) -> tuple[dict, str]:
    stripped = raw.lstrip()
    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise FrontmatterParseError("Missing YAML frontmatter (must start with ---)")

    closing_line = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_line = index
            break

    if closing_line is None:
        raise FrontmatterParseError(
            "Unclosed YAML frontmatter (missing closing ---)"
        )

    yaml_block = "".join(lines[1:closing_line])
    body = "".join(lines[closing_line + 1:]).lstrip("\n")

    try:
        meta = yaml.safe_load(yaml_block)
    except yaml.YAMLError as e:
        raise FrontmatterParseError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(meta, dict):
        raise FrontmatterParseError("Frontmatter must be a YAML mapping")

    return meta, body
