"""Docker backend: one container per episode, no network, non-root, resource-limited."""

from __future__ import annotations

import re
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..tasks.schema import Task
from .base import BASE_SNAPSHOT, DIFF_EXCLUDES, ExecResult

IMAGE_PREFIX = "secwright-task"


def image_tag(task: Task, ref: str) -> str:
    safe_ref = re.sub(r"[^A-Za-z0-9_.-]", "_", ref)[:120]
    return f"{IMAGE_PREFIX}/{task.id}:{safe_ref}"


@dataclass
class BuildResult:
    tag: str
    ok: bool
    duration_s: float
    log_tail: str


def build_image(task: Task, ref: str, no_cache: bool = False, timeout_s: int = 1200) -> BuildResult:
    """Build the task environment at an upstream ref (passed to the Dockerfile as REF)."""
    tag = image_tag(task, ref)
    cmd = ["docker", "build", "-t", tag, "--build-arg", f"REF={ref}", "--label", f"secwright.task={task.id}"]
    if no_cache:
        cmd.append("--no-cache")
    cmd.append(str(task.environment_dir))
    t0 = time.monotonic()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    return BuildResult(tag, p.returncode == 0, time.monotonic() - t0, (p.stdout + p.stderr)[-4000:])


class DockerSandbox:
    def __init__(
        self,
        image: str,
        workdir: str = "/work",
        cpus: float = 2,
        memory: str = "2g",
        pids: int = 512,
        user: str = "agent",
    ):
        self.image = image
        self.workdir = workdir
        self.user = user
        self._limits = ["--cpus", str(cpus), "--memory", memory, "--pids-limit", str(pids)]
        self.name: str | None = None

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        self.name = f"secwright-{uuid.uuid4().hex[:12]}"
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self.name,
                "--network",
                "none",
                "--user",
                self.user,
                "--workdir",
                self.workdir,
                *self._limits,
                "--entrypoint",
                "sleep",
                self.image,
                "infinity",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def close(self) -> None:
        if self.name:
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
            self.name = None

    def __enter__(self) -> DockerSandbox:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- operations ------------------------------------------------------------------------
    def exec(self, cmd: str, timeout_s: int, cwd: str | None = None, user: str | None = None) -> ExecResult:
        assert self.name, "sandbox not started"
        # `timeout` inside the container really kills the command; the outer timeout is a backstop.
        inner = f"timeout -s KILL {int(timeout_s)} bash -c {shlex.quote(cmd)}"
        args = [
            "docker",
            "exec",
            "-w",
            cwd or self.workdir,
            "-u",
            user or self.user,
            self.name,
            "bash",
            "-c",
            inner,
        ]
        t0 = time.monotonic()
        try:
            p = subprocess.run(args, capture_output=True, timeout=timeout_s + 15)
        except subprocess.TimeoutExpired as e:
            return ExecResult(-1, _dec(e.stdout), _dec(e.stderr), True, time.monotonic() - t0)
        timed_out = p.returncode == 137 and time.monotonic() - t0 >= timeout_s
        return ExecResult(p.returncode, _dec(p.stdout), _dec(p.stderr), timed_out, time.monotonic() - t0)

    def read_file(self, path: str) -> bytes:
        assert self.name, "sandbox not started"
        p = subprocess.run(
            ["docker", "exec", "-u", self.user, self.name, "cat", "--", path], capture_output=True
        )
        if p.returncode != 0:
            raise FileNotFoundError(_dec(p.stderr).strip() or path)
        return p.stdout

    def write_file(self, path: str, data: bytes) -> None:
        assert self.name, "sandbox not started"
        p = subprocess.run(
            ["docker", "exec", "-i", "-u", self.user, self.name, "sh", "-c", 'cat > "$1"', "sh", path],
            input=data,
            capture_output=True,
        )
        if p.returncode != 0:
            raise OSError(_dec(p.stderr).strip() or f"cannot write {path}")

    def copy_in(self, src: Path, dest: str) -> None:
        """Copy a host directory in, owned by root, so the agent user can read but not modify it."""
        assert self.name, "sandbox not started"
        subprocess.run(["docker", "cp", f"{src}/.", f"{self.name}:{dest}"], check=True, capture_output=True)
        self.exec(
            f"chown -R root:root {shlex.quote(dest)} && chmod -R a+rX,go-w {shlex.quote(dest)}",
            timeout_s=30,
            user="root",
        )

    def diff(self) -> str:
        """Unified diff of the workdir against the read-only starting snapshot."""
        excludes = " ".join(f"-x {shlex.quote(x)}" for x in DIFF_EXCLUDES)
        r = self.exec(f"diff -ruN {excludes} {BASE_SNAPSHOT} {self.workdir}", timeout_s=60, cwd="/")
        if r.exit_code not in (0, 1):  # 1 just means "files differ"
            raise RuntimeError(f"diff failed: {r.stderr.strip()}")
        out = r.stdout.replace(f"{BASE_SNAPSHOT}/", "a/").replace(f"{self.workdir}/", "b/")
        # Drop timestamps from ---/+++ headers so identical edits give identical diffs.
        return re.sub(r"^((?:---|\+\+\+) \S+)\t.*$", r"\1", out, flags=re.M)


def _dec(b: bytes | str | None) -> str:
    if b is None:
        return ""
    return b if isinstance(b, str) else b.decode("utf-8", errors="replace")
