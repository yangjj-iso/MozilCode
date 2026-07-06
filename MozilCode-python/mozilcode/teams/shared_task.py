from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mozilcode.teams.fields import string_field, string_list_field


VALID_TASK_STATUSES = {"pending", "in_progress", "completed", "blocked"}


def _task_string_field(
    data: dict[str, Any],
    name: str,
    *,
    default: str = "",
    required: bool = False,
) -> str:
    return string_field(
        data,
        name,
        prefix="task",
        default=default,
        required=required,
    )


@dataclass
class SharedTask:
    id: str
    title: str
    description: str = ""
    status: str = "pending"  # pending | in_progress | completed | blocked
    assignee: str = ""
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    created_by: str = ""


    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SharedTask:
        if not isinstance(data, dict):
            raise ValueError("task must be an object")
        status = _task_string_field(data, "status", default="pending")
        if status not in VALID_TASK_STATUSES:
            raise ValueError(
                f"task.status must be one of: "
                f"{', '.join(sorted(VALID_TASK_STATUSES))}"
            )
        return cls(
            id=_task_string_field(data, "id", required=True),
            title=_task_string_field(data, "title", required=True),
            description=_task_string_field(data, "description"),
            status=status,
            assignee=_task_string_field(data, "assignee"),
            blocks=string_list_field(data, "blocks", prefix="task"),
            blocked_by=string_list_field(data, "blocked_by", prefix="task"),
            created_by=_task_string_field(data, "created_by"),
        )


class SharedTaskStore:


    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._next_id = 1
        self._tasks: dict[str, SharedTask] = {}
        self._load()

    def _load(self) -> None:
        self._next_id = 1
        self._tasks = {}
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return

        max_numeric_id = 0
        raw_tasks = data.get("tasks", [])
        for item in raw_tasks if isinstance(raw_tasks, list) else []:
            try:
                task = SharedTask.from_dict(item)
            except ValueError:
                continue
            self._tasks[task.id] = task
            if task.id.isdigit():
                max_numeric_id = max(max_numeric_id, int(task.id))

        raw_next_id = data.get("next_id", max_numeric_id + 1)
        if (
            isinstance(raw_next_id, int)
            and not isinstance(raw_next_id, bool)
            and raw_next_id > 0
        ):
            self._next_id = max(raw_next_id, max_numeric_id + 1)
        else:
            self._next_id = max(1, max_numeric_id + 1)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "next_id": self._next_id,
            "tasks": [t.to_dict() for t in self._tasks.values()],
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create(
        self,
        title: str,
        description: str = "",
        assignee: str = "",
        blocks: list[str] | None = None,
        blocked_by: list[str] | None = None,
        created_by: str = "",
    ) -> SharedTask:
        self._load()
        task_id = str(self._next_id)
        self._next_id += 1
        task = SharedTask(
            id=task_id,
            title=title,
            description=description,
            assignee=assignee,
            blocks=blocks or [],
            blocked_by=blocked_by or [],
            created_by=created_by,
        )
        self._tasks[task_id] = task
        self._save()
        return task

    def get(self, task_id: str) -> SharedTask | None:
        self._load()
        return self._tasks.get(task_id)


    def list_tasks(
        self,
        status: str | None = None,
        assignee: str | None = None,
    ) -> list[SharedTask]:
        self._load()
        result = list(self._tasks.values())
        if status:
            result = [t for t in result if t.status == status]
        if assignee:
            result = [t for t in result if t.assignee == assignee]
        return result


    def update(
        self,
        task_id: str,
        status: str | None = None,
        assignee: str | None = None,
        description: str | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> SharedTask | None:
        self._load()
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if status is not None:
            if status not in VALID_TASK_STATUSES:
                raise ValueError(
                    f"status must be one of: {', '.join(sorted(VALID_TASK_STATUSES))}"
                )
            task.status = status
        if assignee is not None:
            task.assignee = assignee
        if description is not None:
            task.description = description
        if add_blocks:
            for bid in add_blocks:
                if bid not in task.blocks:
                    task.blocks.append(bid)
        if add_blocked_by:
            for bid in add_blocked_by:
                if bid not in task.blocked_by:
                    task.blocked_by.append(bid)
        self._save()
        return task

    def init_empty(self) -> None:
        self._tasks.clear()
        self._next_id = 1
        self._save()
