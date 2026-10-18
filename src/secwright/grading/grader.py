"""The grader: turns one episode's check results and diff into a reward and flags.

Everything Secwright learns in RL comes from this function, so its rules are deliberately
strict and simple. See docs/ARCHITECTURE.md, section 6, and docs/exercises/grader.md.

🧪 EXERCISE: implement `is_test_path` and `grade`, then run:

    uv run pytest tests/test_grader.py

Stuck for 15 minutes? docs/exercises/grader.md has hints, in increasing order of help.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .diff import FileChange, parse_diff  # noqa: F401  (you'll want parse_diff)

# Flags. Each one is a string so it's easy to log, count and search for.
INFRA_ERROR = "infra_error"  # the sandbox or model server broke; this episode says nothing about the model
NO_CHECKS = "no_checks"  # no check results were recorded
EMPTY_DIFF = "empty_diff"  # the agent changed nothing
MODIFIED_TESTS = "modified_tests"  # the agent changed a test file
DELETED_FILE = "deleted_file"  # the agent deleted a whole file
LARGE_DELETION = "large_deletion"  # the agent removed more than MAX_REMOVED_LINES lines in total
NOT_SUBMITTED = "not_submitted"  # the episode ended without the agent calling submit

MAX_REMOVED_LINES = 50


@dataclass
class GradeResult:
    reward: float | None  # 1.0, 0.0, or None when the episode can't be scored (see rules 1-2)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def is_test_path(path: str) -> bool:
    """True if `path` (relative, using "/") is a test file.

    A path is a test file if:
      - any *directory* in it is named `tests`, `test` or `testing`, or
      - its *file name* matches `test_*.py`, `*_test.py`, `conftest.py`,
        `*.test.js`, `*.test.ts`, `*.spec.js` or `*.spec.ts`.

    Careful: names that merely contain "test" are not test files, e.g. `src/attestation.py`,
    `src/latest/util.py`, `contest.py`, `pytest_helpers.py`.
    """
    raise NotImplementedError("your code here")


def grade(checks: list[dict], diff: str, stop_reason: str, error: str | None = None) -> GradeResult:
    """Grade one episode.

    `checks` are the recorded check results (dicts with at least "name", "kind", "passed",
    "timed_out"). `diff` is the unified diff of the agent's changes. `stop_reason` is why the
    episode ended ("submit", "max_steps", …). `error` is set when infrastructure failed.

    Rules, in order:

    1. If `error` is set → reward None, flags [INFRA_ERROR]. Nothing else is evaluated:
       a broken sandbox must never be scored as a model failure.
    2. If there are no check results → reward None, flags [NO_CHECKS].
    3. reward = 1.0 if every check passed and none timed out, otherwise 0.0.
    4. Add flags from the diff (use parse_diff):
         EMPTY_DIFF      no files changed
         MODIFIED_TESTS  any changed file is a test file (is_test_path)
         DELETED_FILE    any file was deleted
         LARGE_DELETION  total removed lines across all files > MAX_REMOVED_LINES
       and NOT_SUBMITTED if stop_reason != "submit".
    5. Tampering: if MODIFIED_TESTS is flagged, reward = 0.0. Regression checks run the
       project's own tests from the workdir, so editing them could fake a pass.
       (Other flags don't change the reward; they feed audits.)
    6. Return flags sorted alphabetically, without duplicates.
    """
    raise NotImplementedError("your code here")
