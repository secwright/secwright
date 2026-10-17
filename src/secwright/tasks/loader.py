"""Find and load tasks from the tasks/ tree."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .schema import Task


def tasks_root() -> Path:
    """The tasks/ directory: $SECWRIGHT_TASKS, else ./tasks found from the cwd upwards."""
    env = os.environ.get("SECWRIGHT_TASKS")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "tasks").is_dir() and (d / "pyproject.toml").exists():
            return d / "tasks"
    raise FileNotFoundError("no tasks/ directory found; run from the repo or set SECWRIGHT_TASKS")


def load_task_file(path: Path) -> Task:
    data = yaml.safe_load(path.read_text())
    task = Task.model_validate(data)
    if task.id != path.parent.name:
        raise ValueError(f"{path}: id {task.id!r} doesn't match folder name {path.parent.name!r}")
    if task.family != path.parent.parent.name:
        raise ValueError(f"{path}: family {task.family!r} doesn't match folder {path.parent.parent.name!r}")
    return task.model_copy(update={"path": path.parent})


def list_tasks(root: Path | None = None) -> list[Task]:
    root = root or tasks_root()
    return [load_task_file(p) for p in sorted(root.glob("*/*/task.yaml"))]


def load_task(task_id: str, root: Path | None = None) -> Task:
    root = root or tasks_root()
    matches = list(root.glob(f"*/{task_id}/task.yaml"))
    if not matches:
        raise KeyError(f"no task {task_id!r} under {root}")
    return load_task_file(matches[0])
