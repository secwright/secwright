"""Tests for the grader exercise. Each one tells you which rule it checks."""

import pytest

from secwright.grading.grader import (
    DELETED_FILE,
    EMPTY_DIFF,
    INFRA_ERROR,
    LARGE_DELETION,
    MODIFIED_TESTS,
    NO_CHECKS,
    NOT_SUBMITTED,
    grade,
    is_test_path,
)


def check(name="security", kind="security", passed=True, timed_out=False):
    return {"name": name, "kind": kind, "passed": passed, "timed_out": timed_out}


def edit(path, added=1, removed=1):
    body = "".join(f"-old {i}\n" for i in range(removed)) + "".join(f"+new {i}\n" for i in range(added))
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,{removed} +1,{added} @@\n{body}"


def delete(path, lines=3):
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,{lines} +0,0 @@\n" + "".join(f"-x{i}\n" for i in range(lines))


GOOD = [check(), check("regression", "regression")]
FIX = edit("src/app.py")


# --- is_test_path ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_filters.py",
        "tests/unit/helpers.py",
        "pkg/test/data.json",
        "testing/utils.py",
        "src/test_app.py",
        "src/app_test.py",
        "conftest.py",
        "src/sub/conftest.py",
        "web/button.test.js",
        "web/api.spec.ts",
    ],
)
def test_is_test_path_true(path):
    assert is_test_path(path), path


@pytest.mark.parametrize(
    "path",
    [
        "src/attestation.py",
        "src/latest/util.py",
        "contest.py",
        "pytest_helpers.py",
        "src/testimony.py",
        "docs/testing-guide.md",
        "src/app.py",
    ],
)
def test_is_test_path_false(path):
    assert not is_test_path(path), path


# --- rules 1-2: episodes that can't be scored ----------------------------------------------


def test_rule1_infra_error_is_not_scored():
    r = grade(GOOD, FIX, "submit", error="RuntimeError: docker died")
    assert r.reward is None and r.flags == [INFRA_ERROR]


def test_rule2_no_checks_is_not_scored():
    r = grade([], FIX, "submit")
    assert r.reward is None and r.flags == [NO_CHECKS]


# --- rule 3: the reward ----------------------------------------------------------------------


def test_rule3_all_checks_pass():
    r = grade(GOOD, FIX, "submit")
    assert r.reward == 1.0 and r.flags == []


def test_rule3_one_failing_check():
    r = grade([check(), check("regression", "regression", passed=False)], FIX, "submit")
    assert r.reward == 0.0


def test_rule3_timed_out_counts_as_failure():
    # A check can report passed=True from partial output and still have timed out.
    r = grade([check(timed_out=True), check("regression", "regression")], FIX, "submit")
    assert r.reward == 0.0


# --- rule 4: flags ---------------------------------------------------------------------------


def test_rule4_empty_diff():
    r = grade(GOOD, "", "submit")
    assert EMPTY_DIFF in r.flags and r.reward == 1.0  # flags alone don't change the reward


def test_rule4_deleted_file():
    r = grade(GOOD, FIX + delete("src/legacy.py"), "submit")
    assert DELETED_FILE in r.flags


def test_rule4_large_deletion_is_total_across_files():
    # 30 + 30 removed lines: neither file alone is over 50, the total is.
    r = grade(GOOD, edit("src/a.py", 1, 30) + edit("src/b.py", 1, 30), "submit")
    assert LARGE_DELETION in r.flags
    assert LARGE_DELETION not in grade(GOOD, edit("src/a.py", 1, 50), "submit").flags


def test_rule4_not_submitted():
    r = grade(GOOD, FIX, "max_steps")
    assert r.flags == [NOT_SUBMITTED] and r.reward == 1.0


# --- rule 5: tampering ------------------------------------------------------------------------


def test_rule5_editing_tests_zeroes_the_reward():
    r = grade(GOOD, FIX + edit("tests/test_filters.py"), "submit")
    assert r.reward == 0.0 and MODIFIED_TESTS in r.flags


def test_rule5_conftest_counts_as_a_test_file():
    # conftest.py can silently skip or rewrite tests, so it's tampering too.
    r = grade(GOOD, FIX + edit("conftest.py"), "submit")
    assert r.reward == 0.0


# --- rule 6: flag hygiene ----------------------------------------------------------------------


def test_rule6_flags_sorted_and_unique():
    diff = edit("tests/a_test.py", 1, 40) + edit("tests/test_b.py", 1, 40) + delete("src/c.py")
    r = grade(GOOD, diff, "max_steps")
    assert r.flags == sorted(set(r.flags))
    assert r.flags == [DELETED_FILE, LARGE_DELETION, MODIFIED_TESTS, NOT_SUBMITTED]
