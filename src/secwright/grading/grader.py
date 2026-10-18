"""The grader: turns one episode's check results and diff into a reward and flags.

Everything Secwright learns in RL comes from this function, so its rules are deliberately
strict and simple. See docs/ARCHITECTURE.md (section 6) and docs/GRADING.md.
"""

from __future__ import annotations

import fnmatch
from dataclasses import asdict, dataclass, field

from .diff import parse_diff

# Flags. Each one is a string so it's easy to log, count and search for.
INFRA_ERROR = "infra_error"  # the sandbox or model server broke; this episode says nothing about the model
NO_CHECKS = "no_checks"  # no check results were recorded
EMPTY_DIFF = "empty_diff"  # the agent changed nothing
MODIFIED_TESTS = "modified_tests"  # the agent changed a test file
DELETED_FILE = "deleted_file"  # the agent deleted a whole file
LARGE_DELETION = "large_deletion"  # the agent removed more than MAX_REMOVED_LINES lines in total
NOT_SUBMITTED = "not_submitted"  # the episode ended without the agent calling submit

MAX_REMOVED_LINES = 50

TEST_DIRS = {"tests", "test", "testing"}
TEST_FILE_PATTERNS = (
    "test_*.py",
    "*_test.py",
    "conftest.py",
    "*.test.js",
    "*.test.ts",
    "*.spec.js",
    "*.spec.ts",
)


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
    *dirs, name = path.split("/")
    # Whole directory names and whole-file patterns only: never search for the substring "test".
    if any(d in TEST_DIRS for d in dirs):
        return True
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in TEST_FILE_PATTERNS)


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
    # Rules 1-2: episodes that can't be scored.
    if error is not None:
        return GradeResult(None, [INFRA_ERROR])
    if not checks:
        return GradeResult(None, [NO_CHECKS])

    # Rule 3: all checks passed, and none timed out (partial output can look like a pass).
    reward = 1.0 if all(c["passed"] and not c.get("timed_out", False) for c in checks) else 0.0

    # Rule 4: flags from the diff and the stop reason.
    files = parse_diff(diff)
    flags: set[str] = set()
    if not files:
        flags.add(EMPTY_DIFF)
    if any(is_test_path(f.path) for f in files):
        flags.add(MODIFIED_TESTS)
    if any(f.deleted for f in files):
        flags.add(DELETED_FILE)
    if sum(f.removed for f in files) > MAX_REMOVED_LINES:
        flags.add(LARGE_DELETION)
    if stop_reason != "submit":
        flags.add(NOT_SUBMITTED)

    # Rule 5: editing tests could fake the regression check, so it never earns reward.
    if MODIFIED_TESTS in flags:
        reward = 0.0

    # Rule 6.
    return GradeResult(reward, sorted(flags))
