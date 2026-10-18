"""The core tools every task family gets: run, read_file, search, edit_file, create_file, submit."""

from __future__ import annotations

import posixpath
import shlex

from ..sandbox.base import Sandbox
from .registry import Tool, ToolError, ToolRegistry, ToolResult, truncate

MAX_READ_LINES = 400
MAX_SEARCH_MATCHES = 100


def _resolve(sandbox: Sandbox, path: str) -> str:
    """Make a path absolute inside the workdir and refuse anything that escapes it."""
    if not path:
        raise ToolError("path is empty")
    full = posixpath.normpath(path if path.startswith("/") else posixpath.join(sandbox.workdir, path))
    root = posixpath.normpath(sandbox.workdir)
    if full != root and not full.startswith(root + "/"):
        raise ToolError(f"{path!r} is outside the project directory {root}")
    return full


def _rel(sandbox: Sandbox, full: str) -> str:
    return posixpath.relpath(full, sandbox.workdir)


def _read_text(sandbox: Sandbox, full: str) -> str:
    try:
        data = sandbox.read_file(full)
    except FileNotFoundError as e:
        raise ToolError(f"cannot read {_rel(sandbox, full)}: {e}") from e
    if b"\0" in data[:8000]:
        raise ToolError(f"{_rel(sandbox, full)} looks like a binary file")
    return data.decode("utf-8", errors="replace")


def _numbered(lines: list[str], start: int) -> str:
    width = len(str(start + len(lines)))
    return "\n".join(f"{i:>{width}}  {line}" for i, line in enumerate(lines, start))


# --- handlers ----------------------------------------------------------------------------


def make_run(step_timeout_s: int):
    def run(sb: Sandbox, args: dict) -> ToolResult:
        cmd = str(args["command"])
        r = sb.exec(cmd, timeout_s=step_timeout_s)
        out = r.stdout + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")
        status = f"timed out after {step_timeout_s}s" if r.timed_out else f"exit code {r.exit_code}"
        return ToolResult(f"[{status}]\n{truncate(out)}", is_error=False)

    return run


def read_file(sb: Sandbox, args: dict) -> ToolResult:
    full = _resolve(sb, str(args["path"]))
    lines = _read_text(sb, full).splitlines()
    start = max(1, int(args.get("start_line") or 1))
    end = int(args.get("end_line") or (start + MAX_READ_LINES - 1))
    end = min(end, start + MAX_READ_LINES - 1, len(lines))
    if start > max(len(lines), 1):
        raise ToolError(f"start_line {start} is past the end of the file ({len(lines)} lines)")
    body = _numbered(lines[start - 1 : end], start)
    more = f"\n… file has {len(lines)} lines; showing {start}-{end}" if end < len(lines) else ""
    return ToolResult(f"{_rel(sb, full)}\n{body}{more}")


def search(sb: Sandbox, args: dict) -> ToolResult:
    pattern = str(args["pattern"])
    target = _resolve(sb, str(args.get("path") or "."))
    cmd = (
        f"rg --line-number --no-heading --color never --max-columns 300 -e {shlex.quote(pattern)} "
        f"{shlex.quote(target)} | head -n {MAX_SEARCH_MATCHES + 1}"
    )
    r = sb.exec(cmd, timeout_s=60)
    lines = [ln.replace(sb.workdir.rstrip("/") + "/", "", 1) for ln in r.stdout.splitlines()]
    if not lines:
        return ToolResult(f"no matches for {pattern!r}")
    note = (
        f"\n… more than {MAX_SEARCH_MATCHES} matches; narrow the pattern or path"
        if len(lines) > MAX_SEARCH_MATCHES
        else ""
    )
    return ToolResult(truncate("\n".join(lines[:MAX_SEARCH_MATCHES]) + note))


def edit_file(sb: Sandbox, args: dict) -> ToolResult:
    full = _resolve(sb, str(args["path"]))
    old, new = str(args["old"]), str(args["new"])
    if not old:
        raise ToolError("'old' is empty; to create a file use create_file")
    text = _read_text(sb, full)
    count = text.count(old)
    if count == 0:
        raise ToolError(
            "'old' was not found; read the file again and copy the exact text, including indentation"
        )
    if count > 1:
        raise ToolError(f"'old' appears {count} times; include more surrounding lines so it is unique")
    updated = text.replace(old, new, 1)
    sb.write_file(full, updated.encode())
    first = text[: text.index(old)].count("\n") + 1
    shown = updated.splitlines()[max(0, first - 3) : first + new.count("\n") + 3]
    return ToolResult(f"edited {_rel(sb, full)}\n{_numbered(shown, max(1, first - 2))}")


def create_file(sb: Sandbox, args: dict) -> ToolResult:
    full = _resolve(sb, str(args["path"]))
    if sb.exec(f"test -e {shlex.quote(full)}", timeout_s=10).exit_code == 0:
        raise ToolError(f"{_rel(sb, full)} already exists; use edit_file to change it")
    sb.exec(f"mkdir -p {shlex.quote(posixpath.dirname(full))}", timeout_s=10)
    sb.write_file(full, str(args["content"]).encode())
    return ToolResult(f"created {_rel(sb, full)}")


def submit(sb: Sandbox, args: dict) -> ToolResult:
    return ToolResult("submitted", ends_episode=True)


# --- registry ----------------------------------------------------------------------------


def core_tools(step_timeout_s: int = 60) -> ToolRegistry:
    path = {"type": "string", "description": "file path, relative to the project directory"}
    return ToolRegistry(
        [
            Tool(
                "run",
                "Run a shell command in the project directory (bash). Use it to list files, run tests, "
                "or inspect the environment. There is no network access.",
                {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
                make_run(step_timeout_s),
            ),
            Tool(
                "read_file",
                f"Read a text file with line numbers, up to {MAX_READ_LINES} lines per call.",
                {
                    "type": "object",
                    "properties": {
                        "path": path,
                        "start_line": {"type": "integer", "description": "first line, 1-based"},
                        "end_line": {"type": "integer", "description": "last line, inclusive"},
                    },
                    "required": ["path"],
                },
                read_file,
            ),
            Tool(
                "search",
                "Search the project for a regular expression (ripgrep). Returns file:line:text matches.",
                {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {**path, "description": "optional"},
                    },
                    "required": ["pattern"],
                },
                search,
            ),
            Tool(
                "edit_file",
                "Replace one exact, unique occurrence of `old` with `new` in a file. Copy `old` exactly, "
                "including indentation, and include enough context to make it unique.",
                {
                    "type": "object",
                    "properties": {"path": path, "old": {"type": "string"}, "new": {"type": "string"}},
                    "required": ["path", "old", "new"],
                },
                edit_file,
            ),
            Tool(
                "create_file",
                "Create a new file with the given content. Fails if the file already exists.",
                {
                    "type": "object",
                    "properties": {"path": path, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
                create_file,
            ),
            Tool(
                "submit",
                "Finish the task. Call this once your change is complete and you have checked it.",
                {
                    "type": "object",
                    "properties": {"summary": {"type": "string", "description": "one or two sentences"}},
                    "required": ["summary"],
                },
                submit,
            ),
        ]
    )
