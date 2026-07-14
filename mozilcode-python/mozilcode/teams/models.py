"""团队与队友数据模型。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from mozilcode.teams.fields import optional_bool_field, string_field
from mozilcode.teams.mailbox import validate_mailbox_id
from mozilcode.teams.progress import TeammateProgress


class BackendType(str, Enum):
    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


@dataclass
class TeammateInfo:
    name: str
    agent_id: str
    agent_type: str
    model: str
    worktree_path: str
    backend_type: str  # BackendType value
    is_active: bool | None = None
    progress: Optional[TeammateProgress] = None

    def to_dict(self) -> dict:
        # Exclude progress (runtime-only, contains threading.Lock)
        return {
            "name": self.name,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "backend_type": self.backend_type,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TeammateInfo:
        if not isinstance(data, dict):
            raise ValueError("teammate must be an object")
        backend_type = _team_string_field(data, "backend_type")
        if backend_type not in {item.value for item in BackendType}:
            raise ValueError("teammate.backend_type is invalid")
        is_active = optional_bool_field(data, "is_active", prefix="teammate")
        return cls(
            name=_team_string_field(data, "name"),
            agent_id=validate_mailbox_id(
                _team_string_field(data, "agent_id"),
                "agent_id",
            ),
            agent_type=_team_string_field(data, "agent_type"),
            model=_team_string_field(data, "model", required=False),
            worktree_path=_team_string_field(data, "worktree_path", required=False),
            backend_type=backend_type,
            is_active=is_active,
        )


def _team_string_field(data: dict[str, Any], name: str, *, required: bool = True) -> str:
    return string_field(data, name, prefix="team", required=required)


def _sanitize_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "team"


@dataclass
class AgentTeam:
    name: str
    lead_agent_id: str
    members: list[TeammateInfo] = field(default_factory=list)
    config_path: str = ""
    description: str = ""

    def get_member(self, name: str) -> TeammateInfo | None:
        for m in self.members:
            if m.name == name or m.agent_id == name:
                return m
        return None


    def add_member(self, member: TeammateInfo) -> None:
        self.members.append(member)

    def remove_member(self, name: str) -> bool:
        for i, m in enumerate(self.members):
            if m.name == name or m.agent_id == name:
                self.members.pop(i)
                return True
        return False


    def set_member_active(self, name: str, is_active: bool | None) -> bool:
        member = self.get_member(name)
        if member is None:
            return False
        member.is_active = is_active
        return True

    def all_idle(self) -> bool:
        return all(m.is_active is False for m in self.members)


    def active_members(self) -> list[TeammateInfo]:
        return [m for m in self.members if m.is_active is not False]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lead_agent_id": self.lead_agent_id,
            "members": [m.to_dict() for m in self.members],
            "config_path": self.config_path,
            "description": self.description,
        }


    @classmethod
    def from_dict(cls, data: dict) -> AgentTeam:
        if not isinstance(data, dict):
            raise ValueError("team config must be an object")
        raw_members = data.get("members", [])
        if not isinstance(raw_members, list):
            raise ValueError("team.members must be a list")
        members: list[TeammateInfo] = []
        for item in raw_members:
            try:
                members.append(TeammateInfo.from_dict(item))
            except ValueError:
                continue
        return cls(
            name=_team_string_field(data, "name"),
            lead_agent_id=validate_mailbox_id(
                _team_string_field(data, "lead_agent_id"),
                "lead_agent_id",
            ),
            members=members,
            config_path=_team_string_field(data, "config_path", required=False),
            description=_team_string_field(data, "description", required=False),
        )

    def save(self) -> None:
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, config_path: str) -> AgentTeam:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        team = cls.from_dict(data)
        team.config_path = config_path
        return team


def resolve_team_dir(team_name: str) -> Path:
    slug = _sanitize_name(team_name)
    return Path.home() / ".mozilcode" / "teams" / slug


def unique_team_name(team_name: str) -> str:
    slug = _sanitize_name(team_name)
    base_dir = Path.home() / ".mozilcode" / "teams"
    if not (base_dir / slug).exists():
        return slug
    counter = 2
    while (base_dir / f"{slug}-{counter}").exists():
        counter += 1
    return f"{slug}-{counter}"
