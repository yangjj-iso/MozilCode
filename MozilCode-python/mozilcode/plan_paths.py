from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
import random

ADJECTIVES: tuple[str, ...] = (
    "bold",
    "bright",
    "calm",
    "cool",
    "deep",
    "fair",
    "fast",
    "fine",
    "glad",
    "keen",
    "kind",
    "lean",
    "mild",
    "neat",
    "pure",
    "safe",
    "slim",
    "soft",
    "tall",
    "warm",
    "wise",
    "grand",
    "swift",
    "vivid",
)

NOUNS: tuple[str, ...] = (
    "sketch",
    "draft",
    "spark",
    "bloom",
    "trail",
    "ridge",
    "creek",
    "grove",
    "cliff",
    "cove",
    "field",
    "forge",
    "frost",
    "haven",
    "pearl",
    "stone",
    "storm",
    "river",
    "tower",
    "delta",
    "flame",
    "orbit",
    "pulse",
    "shore",
)


def plan_directory(work_dir: str | Path) -> Path:
    return Path(work_dir) / ".mozilcode" / "plans"


def generate_plan_slug(
    *,
    now: datetime | None = None,
    chooser: Callable[[Sequence[str]], str] = random.choice,
) -> str:
    timestamp = (now or datetime.now()).strftime("%m%d-%H%M")
    return f"{chooser(ADJECTIVES)}-{chooser(NOUNS)}-{timestamp}"


def create_plan_path(
    work_dir: str | Path,
    *,
    now: datetime | None = None,
    chooser: Callable[[Sequence[str]], str] = random.choice,
) -> Path:
    directory = plan_directory(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{generate_plan_slug(now=now, chooser=chooser)}.md"
