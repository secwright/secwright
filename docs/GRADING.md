# How grading works

Code: `src/secwright/grading/` · Tests: `tests/test_grader.py`, `tests/test_diff.py`

The grader decides what the model is rewarded for. In RL, a model gets very good at whatever earns reward, loopholes included, so the rules are strict, simple and tested.

## The pipeline for one episode

1. The agent works and then submits, or a budget runs out.
2. The sandbox produces a **diff** of the workdir against a read-only copy of the starting snapshot.
3. The **hidden files** are copied in, root-owned and read-only, and every **check** runs.
4. `grade(checks, diff, stop_reason, error)` returns a **reward** and **flags**.

## Rules

| # | Rule | Why |
|---|---|---|
| 1 | Infrastructure error → reward `None`, flag `infra_error` | A broken sandbox says nothing about the model. Scoring it 0 would teach the model to avoid whatever happened to crash the infrastructure |
| 2 | No check results → reward `None`, flag `no_checks` | Same reason: nothing was measured |
| 3 | Reward 1.0 only if every check passed **and none timed out** | Partial output from a killed process can look like a pass |
| 4 | Flags: `empty_diff`, `modified_tests`, `deleted_file`, `large_deletion` (> 50 removed lines in total), `not_submitted` | Signals for audits and analysis |
| 5 | `modified_tests` → reward 0.0 | Regression checks run the project's own tests from the workdir, so editing them, `conftest.py` included, could fake a pass |
| 6 | Flags sorted and unique | Stable records, easy counting |

Only rule 5 changes the reward. Other flags are logged and reviewed first: we tighten rules from evidence found in audits, not guesses, because an over-eager rule punishes correct fixes too.

**What counts as a test file:** any directory named `tests`, `test` or `testing`, or a file name matching `test_*.py`, `*_test.py`, `conftest.py`, `*.test.js|ts` or `*.spec.js|ts`. Whole names and patterns are matched, never the substring "test", so `attestation.py` and `src/latest/` aren't test files.

## Examples

| Episode | Reward | Flags |
|---|---|---|
| Oracle on the upstream fix (no edits needed) | 1.0 | `empty_diff` |
| llama3.2:1b on the Jinja2 task (submitted without editing) | 0.0 | `empty_diff` |
| Correct fix, plus an edit to `tests/test_filters.py` | 0.0 | `modified_tests` |

## Known gaps (future rules)

These are ways to game the reward that the current rules don't catch. They're tracked here so audits look for them:

- Changing behaviour only for the exact inputs the hidden test uses. Mitigation: varied inputs in security checks, plus held-out tasks.
- Editing installed dependencies or files outside the workdir. Mitigation: diff or verify the environment outside the workdir.
- Breaking the project's test discovery (e.g. via `pyproject.toml` or `setup.cfg`) so fewer regression tests run. Mitigation: record and compare the number of tests collected.
