import shutil
import subprocess
import time
from pathlib import Path

import pytest

from secwright.sandbox.base import ExecResult


class DirSandbox:
    """A test double: a temp directory standing in for the container's workdir."""

    def __init__(self, root: Path):
        self.root = root
        self.workdir = "/work"

    def _host(self, path: str) -> Path:
        assert path.startswith(self.workdir), path
        return self.root / path[len(self.workdir) :].lstrip("/")

    def start(self) -> None: ...
    def close(self) -> None: ...

    def exec(self, cmd: str, timeout_s: int, cwd: str | None = None) -> ExecResult:
        cmd = cmd.replace(self.workdir, str(self.root))
        t0 = time.monotonic()
        p = subprocess.run(
            ["bash", "-c", cmd], cwd=self.root, capture_output=True, text=True, timeout=timeout_s
        )
        return ExecResult(
            p.returncode,
            p.stdout.replace(str(self.root), self.workdir),
            p.stderr,
            False,
            time.monotonic() - t0,
        )

    def read_file(self, path: str) -> bytes:
        p = self._host(path)
        if not p.is_file():
            raise FileNotFoundError(path)
        return p.read_bytes()

    def write_file(self, path: str, data: bytes) -> None:
        p = self._host(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def copy_in(self, src: Path, dest: str) -> None: ...
    def diff(self) -> str:
        return ""


@pytest.fixture
def sandbox(tmp_path: Path) -> DirSandbox:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text(
        "def greet(name):\n    return 'hi ' + name\n\n\ndef bye():\n    return 'bye'\n"
    )
    return DirSandbox(tmp_path)


def docker_available() -> bool:
    return (
        shutil.which("docker") is not None
        and subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    )
