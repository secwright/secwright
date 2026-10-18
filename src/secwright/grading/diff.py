"""Parse the unified diffs that sandboxes produce (`diff -ruN`, paths as a/… and b/…)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


@dataclass
class FileChange:
    path: str  # relative to the workdir, e.g. "src/jinja2/filters.py"
    added: int = 0  # lines added
    removed: int = 0  # lines removed
    created: bool = False  # the file didn't exist before
    deleted: bool = False  # the file no longer exists


def parse_diff(diff: str) -> list[FileChange]:
    """One FileChange per file in the diff, in order.

    Hunk bodies are consumed by count (from each `@@ -a,b +c,d @@` header), so content lines
    that happen to start with `---` or `+++` are never mistaken for file headers.
    """
    changes: list[FileChange] = []
    current: FileChange | None = None
    old_left = new_left = 0  # lines still expected in the current hunk
    saw_old = saw_new = False  # whether any hunk had old / new content

    def close_file() -> None:
        if current is not None:
            current.created = not saw_old
            current.deleted = not saw_new
            changes.append(current)

    for line in diff.splitlines():
        if old_left > 0 or new_left > 0:  # inside a hunk body
            if line.startswith("\\"):  # "\ No newline at end of file"
                continue
            tag = line[:1]
            if tag == "+":
                current.added += 1
                new_left -= 1
            elif tag == "-":
                current.removed += 1
                old_left -= 1
            else:  # context line (" ") or an empty context line
                old_left -= 1
                new_left -= 1
            continue
        if line.startswith("+++ "):
            close_file()
            path = line[4:].split("\t")[0]
            current = FileChange(path[2:] if path.startswith(("a/", "b/")) else path)
            saw_old = saw_new = False
            continue
        m = _HUNK.match(line)
        if m and current is not None:
            old_left = int(m.group(1)) if m.group(1) is not None else 1
            new_left = int(m.group(2)) if m.group(2) is not None else 1
            saw_old |= old_left > 0
            saw_new |= new_left > 0
    close_file()
    return changes
