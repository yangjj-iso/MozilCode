"""计划文件路径生成/解析测试。"""

from __future__ import annotations

from datetime import datetime

from mozilcode.plan_paths import (
    ADJECTIVES,
    NOUNS,
    create_plan_path,
    generate_plan_slug,
    plan_directory,
)


def test_plan_directory_uses_project_mozilcode_plans(tmp_path) -> None:
    assert plan_directory(tmp_path) == tmp_path / ".mozilcode" / "plans"


def test_generate_plan_slug_uses_word_lists_and_timestamp() -> None:
    choices = iter(["bold", "sketch"])

    slug = generate_plan_slug(
        now=datetime(2026, 7, 7, 9, 30),
        chooser=lambda options: next(choices),
    )

    assert slug == "bold-sketch-0707-0930"
    assert "bold" in ADJECTIVES
    assert "sketch" in NOUNS


def test_create_plan_path_creates_directory_and_markdown_path(tmp_path) -> None:
    choices = iter(["calm", "river"])

    path = create_plan_path(
        tmp_path,
        now=datetime(2026, 1, 2, 3, 4),
        chooser=lambda options: next(choices),
    )

    assert path == tmp_path / ".mozilcode" / "plans" / "calm-river-0102-0304.md"
    assert path.parent.is_dir()
