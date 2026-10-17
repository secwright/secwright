"""Run a task's hidden checks inside a sandbox (docs/TASK_FORMAT.md, section 5).

This is the mechanical part of grading: copy the hidden files in, run each check, and record
what happened. Turning check results into a reward, and flagging suspicious diffs, is the
grader's job (grading/grader.py, Phase 1 PR 3).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..sandbox.base import Sandbox
from ..tasks.schema import Task

HIDDEN_MOUNT = "/hidden"


@dataclass
class CheckResult:
    name: str
    kind: str
    passed: bool
    exit_code: int
    timed_out: bool
    duration_s: float
    output_tail: str

    def to_dict(self) -> dict:
        return asdict(self)


def copy_hidden(task: Task, sandbox: Sandbox) -> None:
    """Make hidden/ available read-only at /hidden. Only ever called after the agent is done."""
    if task.hidden_dir.is_dir():
        sandbox.copy_in(task.hidden_dir, HIDDEN_MOUNT)


def run_checks(task: Task, sandbox: Sandbox) -> list[CheckResult]:
    results = []
    for check in task.checks:
        r = sandbox.exec(check.cmd, timeout_s=task.budget.check_timeout_s, cwd=task.workdir)
        tail = (r.stdout + ("\n" + r.stderr if r.stderr else ""))[-4000:]
        results.append(
            CheckResult(check.name, check.kind, r.ok, r.exit_code, r.timed_out, round(r.duration_s, 2), tail)
        )
    return results
