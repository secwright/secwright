"""The sandbox interface (docs/ARCHITECTURE.md, section 3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Where every task image keeps a read-only copy of the starting snapshot. The grader diffs
# against this instead of the workdir's git repo, which the agent can rewrite.
BASE_SNAPSHOT = "/opt/secwright/base"

# Never part of a graded diff.
DIFF_EXCLUDES = (".git", "__pycache__", ".pytest_cache", "*.pyc", ".mypy_cache", ".ruff_cache")


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Sandbox(Protocol):
    workdir: str

    def start(self) -> None: ...
    def exec(self, cmd: str, timeout_s: int, cwd: str | None = None) -> ExecResult: ...
    def read_file(self, path: str) -> bytes: ...
    def write_file(self, path: str, data: bytes) -> None: ...
    def copy_in(self, src: Path, dest: str) -> None: ...
    def diff(self) -> str: ...
    def close(self) -> None: ...
