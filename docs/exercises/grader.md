# Exercise: the grader

**File:** `src/secwright/grading/grader.py` · **Tests:** `uv run pytest tests/test_grader.py`

The grader decides what the model gets rewarded for. In RL, the model gets very good at whatever earns reward, including loopholes, so this small function shapes everything Secwright learns. Read the rules in the docstrings, then write `is_test_path` first (it's self-contained), then `grade`.

Work through the hints only as far as you need. Try for 15 minutes before opening each one.

<details>
<summary>Hint 1: where to start</summary>

- For `is_test_path`, split the path on `/`. The last part is the file name; everything before it is directories. Check the two conditions separately.
- For `grade`, follow the rules in order. Rules 1 and 2 return early, so write them first and run the tests: three of them should pass already.
</details>

<details>
<summary>Hint 2: matching file names</summary>

Python's `fnmatch` module matches shell-style patterns like `test_*.py`. Use `fnmatch.fnmatchcase(name, pattern)`, the case-sensitive version, so behaviour doesn't change between macOS and Linux.

Why do `attestation.py` and `src/latest/util.py` come out false? Because you match the whole file name against a pattern, and check whole directory names for equality. You never search for the substring "test".
</details>

<details>
<summary>Hint 3: computing the flags</summary>

`parse_diff(diff)` gives you a list of `FileChange` objects, each with `path`, `added`, `removed`, `created` and `deleted`.

- `EMPTY_DIFF`: the list is empty.
- `MODIFIED_TESTS`: `any(...)` over the paths.
- `DELETED_FILE`: `any(...)` over `.deleted`.
- `LARGE_DELETION`: `sum(...)` of `.removed`, compared with `MAX_REMOVED_LINES`. It's a *total*, not per file.

Collect the flags in a `set` to avoid duplicates, then return `sorted(...)`.
</details>

<details>
<summary>Hint 4: the reward and the timeout trap</summary>

`reward = 1.0` only if *every* check has `passed` true **and** `timed_out` false. A check that timed out may have printed enough output to look like a pass, so don't trust `passed` alone.

Apply rule 5 *after* computing the flags: if `MODIFIED_TESTS` is in them, the reward becomes 0.0 whatever the checks said.
</details>

## When it's green

Run the whole suite (`uv run pytest`) and a real episode:

```bash
uv run secwright run py-jinja2-cve-2024-22195 --oracle
```

The result line should now show `reward: 1.0` and the flag `empty_diff`. The oracle changes nothing because it runs on the already-fixed version. That's exactly the kind of thing flags are for.

## Questions to think about

1. Why is an infrastructure error scored `None` rather than `0.0`? What would happen to training if broken sandboxes counted as failures?
2. Rule 5 zeroes the reward for editing tests, but other flags only get logged. What's the argument for not zeroing the reward for `large_deletion` too?
3. Can you think of a way to fake a pass that none of these rules catches? (There are some. Write them down; they become future rules and tests.)
