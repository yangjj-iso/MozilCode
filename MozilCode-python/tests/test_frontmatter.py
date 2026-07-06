from __future__ import annotations

import textwrap

import pytest

from mozilcode.frontmatter import FrontmatterParseError, parse_yaml_frontmatter


def test_parse_yaml_frontmatter_accepts_delimiter_text_inside_values() -> None:
    meta, body = parse_yaml_frontmatter(textwrap.dedent("""\
        ---
        name: delimiter
        description: "Use --- as text"
        ---
        Body
    """))

    assert meta == {
        "name": "delimiter",
        "description": "Use --- as text",
    }
    assert body == "Body\n"


def test_parse_yaml_frontmatter_requires_marker_on_own_line() -> None:
    with pytest.raises(FrontmatterParseError, match="Missing YAML frontmatter"):
        parse_yaml_frontmatter("----\nname: bad\n---\nbody")


def test_parse_yaml_frontmatter_rejects_unclosed_block() -> None:
    with pytest.raises(FrontmatterParseError, match="Unclosed YAML"):
        parse_yaml_frontmatter("---\nname: bad\n")
