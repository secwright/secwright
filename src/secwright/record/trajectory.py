"""The trajectory record (docs/ARCHITECTURE.md, section 7). Training reads this format directly."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass
class Trajectory:
    task_id: str
    task_set_version: str
    harness_version: str
    model: dict
    brief_level: str
    messages: list[dict] = field(default_factory=list)
    stop_reason: str = ""
    steps: int = 0
    tokens: dict = field(default_factory=lambda: {"prompt": 0, "completion": 0})
    duration_s: float = 0.0
    diff: str = ""
    checks: list[dict] = field(default_factory=list)
    grade: dict | None = None  # filled in by the grader (grading/grader.py)
    error: str | None = None  # infrastructure problem, if any
    episode_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def append_jsonl(path: Path, traj: Trajectory) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(traj.to_dict(), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
