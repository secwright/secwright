"""Task validation, rules V1–V9 (docs/TASK_FORMAT.md, section 6)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ..grading.checks import CheckResult, copy_hidden, run_checks
from ..sandbox.docker import DockerSandbox, build_image
from .schema import Task

Status = Literal["pass", "fail", "skip"]
MAX_BUILD_S = 600


@dataclass
class RuleResult:
    rule: str
    name: str
    status: Status
    detail: str = ""


@dataclass
class Report:
    task_id: str
    rules: list[RuleResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.status != "fail" for r in self.rules)

    def add(self, rule: str, name: str, status: Status, detail: str = "") -> None:
        self.rules.append(RuleResult(rule, name, status, detail))


def _summary(results: list[CheckResult]) -> str:
    return ", ".join(f"{r.name}={'pass' if r.passed else 'FAIL'}" for r in results)


def _checks_on(
    image: str, task: Task, prepare: Callable[[DockerSandbox], None] | None = None
) -> list[CheckResult]:
    """Fresh sandbox → (optionally apply the reference solution) → hidden files → checks."""
    with DockerSandbox(image, workdir=task.workdir) as sb:
        if prepare:
            prepare(sb)
        copy_hidden(task, sb)
        return run_checks(task, sb)


def _apply_reference_files(task: Task) -> Callable[[DockerSandbox], None]:
    """harden/upgrade: copy reference/ over the workdir, as the agent's own edits would be."""

    def apply(sb: DockerSandbox) -> None:
        for f in sorted(p for p in task.reference_dir.rglob("*") if p.is_file()):
            rel = f.relative_to(task.reference_dir).as_posix()
            sb.write_file(f"{task.workdir}/{rel}", f.read_bytes())

    return apply


def _tree_hash(image: str, task: Task) -> str:
    cmd = "find . -path ./.git -prune -o -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum"
    with DockerSandbox(image, workdir=task.workdir) as sb:
        return sb.exec(cmd, timeout_s=120).stdout.split()[0]


def _leak_check(image: str, task: Task) -> list[str]:
    """V8: hidden/reference files must not be in the image; upstream history must be gone."""
    problems = []
    secret_files = [
        p for d in (task.hidden_dir, task.reference_dir) if d.is_dir() for p in d.rglob("*") if p.is_file()
    ]
    with DockerSandbox(image, workdir=task.workdir) as sb:
        if sb.exec("test ! -e /hidden", timeout_s=10).exit_code != 0:
            problems.append("/hidden exists in the image")
        for f in secret_files:
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            size = f.stat().st_size
            found = sb.exec(
                f"find / -xdev -type f -size {size}c -not -path '/proc/*' 2>/dev/null "
                f"| xargs -r sha256sum 2>/dev/null | grep -m1 {digest}",
                timeout_s=120,
                cwd="/",
            )
            if found.stdout.strip():
                problems.append(f"{f.name} is present in the image at {found.stdout.split()[1]}")
        commits = sb.exec("git rev-list --count HEAD", timeout_s=10).stdout.strip()
        if commits != "1":
            problems.append(f"workdir git repo has {commits or 'no'} commits, expected exactly 1")
    return problems


def validate(task: Task, runs: int = 1, rebuild: bool = False, log: Callable[[str], None] = print) -> Report:
    rep = Report(task.id)
    if task.family == "fix":
        assert task.upstream and task.upstream.fixed_ref
        vuln_ref, fixed_ref = task.upstream.vulnerable_ref, task.upstream.fixed_ref
    else:
        vuln_ref = task.upstream.vulnerable_ref if task.upstream else "task"
        fixed_ref = None
        if not task.reference_dir.is_dir():
            rep.add("V3", "passes after", "fail", "harden/upgrade tasks need a reference/ folder")
            return rep

    # Build (V1, V9) --------------------------------------------------------------------
    log(f"building {task.id} @ {vuln_ref}")
    vb = build_image(task, vuln_ref)
    if not vb.ok:
        rep.add("V1", "builds", "fail", f"vulnerable build failed:\n{vb.log_tail}")
        return rep
    fb = None
    if fixed_ref:
        log(f"building {task.id} @ {fixed_ref}")
        fb = build_image(task, fixed_ref)
        if not fb.ok:
            rep.add("V1", "builds", "fail", f"fixed build failed:\n{fb.log_tail}")
            return rep

    if rebuild:
        log("rebuilding from scratch to compare file trees")
        h1 = _tree_hash(vb.tag, task)
        again = build_image(task, vuln_ref, no_cache=True)
        h2 = _tree_hash(again.tag, task) if again.ok else "build failed"
        rep.add(
            "V1",
            "builds reproducibly",
            "pass" if h1 == h2 else "fail",
            "identical workdir trees" if h1 == h2 else f"tree hash {h1[:12]} != {h2[:12]}",
        )
    else:
        rep.add("V1", "builds reproducibly", "skip", "builds succeeded; run with --rebuild to compare trees")

    # Checks before / after (V2, V3, V4, V6) ----------------------------------------------
    reference = (
        (lambda: _checks_on(fb.tag, task))
        if fb
        else (lambda: _checks_on(vb.tag, task, _apply_reference_files(task)))
    )
    before_runs, after_runs = [], []
    for i in range(runs):
        log(f"run {i + 1}/{runs}: checks on the vulnerable environment")
        before_runs.append(_checks_on(vb.tag, task))
        log(f"run {i + 1}/{runs}: checks on the reference solution")
        after_runs.append(reference())

    before, after = before_runs[0], after_runs[0]
    sec_failed = [r.name for r in before if r.kind == "security" and not r.passed]
    rep.add(
        "V2",
        "fails before",
        "pass" if sec_failed else "fail",
        f"vulnerable: {_summary(before)}" + ("" if sec_failed else " (no security check failed)"),
    )
    rep.add(
        "V3",
        "passes after",
        "pass" if all(r.passed for r in after) else "fail",
        f"reference: {_summary(after)}",
    )
    reg_ok = all(r.passed for r in before + after if r.kind == "regression")
    rep.add(
        "V4",
        "regression holds both ways",
        "pass" if reg_ok else "fail",
        f"vulnerable: {_summary([r for r in before if r.kind == 'regression'])}; "
        f"reference: {_summary([r for r in after if r.kind == 'regression'])}",
    )
    rep.add("V5", "not trivially gameable", "skip", "manual review for now (automated mutation check later)")
    if runs > 1:
        sig = lambda rs: tuple(r.passed for r in rs)  # noqa: E731
        stable = len({sig(r) for r in before_runs}) == 1 and len({sig(r) for r in after_runs}) == 1
        rep.add(
            "V6",
            "deterministic",
            "pass" if stable else "fail",
            f"{runs} runs, results {'identical' if stable else 'differ'}",
        )
    else:
        rep.add("V6", "deterministic", "skip", "run with --runs 3")

    # V7: every check above ran with networking disabled (DockerSandbox uses --network none).
    rep.add("V7", "offline", "pass", "all checks ran with --network none")

    leaks = _leak_check(vb.tag, task)
    rep.add(
        "V8",
        "no leaks",
        "fail" if leaks else "pass",
        "; ".join(leaks) or "no hidden/reference files, 1-commit repo",
    )

    slow = [f"{r.name} {r.duration_s}s" for r in before + after if r.timed_out]
    build_s = max(vb.duration_s, fb.duration_s if fb else 0)
    v9_ok = not slow and build_s < MAX_BUILD_S
    rep.add(
        "V9",
        "within budget",
        "pass" if v9_ok else "fail",
        f"slowest build {build_s:.0f}s (cached builds are fast); "
        + (f"timed out: {', '.join(slow)}" if slow else "no check timed out"),
    )
    return rep


def format_report(rep: Report) -> str:
    icon = {"pass": "✅", "fail": "❌", "skip": "⏭️ "}
    lines = [f"\n{rep.task_id}"]
    for r in rep.rules:
        lines.append(f"  {icon[r.status]} {r.rule} {r.name:<28} {r.detail}")
    lines.append(f"  → {'VALID' if rep.ok else 'INVALID'}")
    return "\n".join(lines)


__all__ = ["Report", "RuleResult", "format_report", "validate"]
