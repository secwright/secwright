# Task format

Status: **draft, Phase 0.** This spec defines what a Secwright training or evaluation task is, how it's laid out on disk, and the rules a task must pass before it's accepted.

## 1. What a task is

A task is one episode of real security work, with an automatic way to judge the result. Every task has:

- **An environment:** a project snapshot the agent works in, built reproducibly.
- **A brief:** what the agent is told, at one of three detail levels.
- **Hidden checks:** commands that decide whether the work succeeded. The agent never sees them.
- **A reference solution:** proof that the task can be solved and that the checks accept a correct solution.

## 2. Families

| Family | Environment | Agent's job | Reference solution |
|---|---|---|---|
| `fix` | Upstream project at a version with a publicly disclosed, already-patched vulnerability | Change the code so it behaves safely | The upstream fixed version (`fixed_ref`) |
| `harden` | A config file written for the task (Dockerfile, Kubernetes manifest, Terraform module) | Make the config pass security policy while keeping it valid | A hardened config written by the task author |
| `upgrade` | A project whose pinned dependency has a published advisory | Move to a safe version without breaking the project | A lockfile or requirements file written by the task author |

`find`, `triage`, `detect` and `alert-triage` will be specified when their phase starts (see [PLAN.md](PLAN.md)).

## 3. Layout

```
tasks/
└── <family>/
    └── <task-id>/
        ├── task.yaml          metadata, brief, checks, budgets
        ├── environment/
        │   └── Dockerfile     builds the snapshot; must not copy hidden/ or reference/
        ├── hidden/            check files, copied in only after the agent submits
        └── reference/         harden/upgrade only: the author's reference solution
```

**Task IDs** are lowercase and unique across the repo: `<ecosystem>-<project>-<advisory-or-slug>`. Examples: `py-jinja2-cve-2024-22195`, `docker-node-app-root-user`, `py-flask-app-requests-upgrade`.

**Upstream code is never committed.** The Dockerfile fetches it from the upstream repo at an exact ref. Files in `hidden/` and `reference/` are written by the task author and licensed with the project.

## 4. `task.yaml`

```yaml
schema_version: 1
id: py-jinja2-cve-2024-22195
family: fix
title: Unsafe attribute keys accepted by the xmlattr filter

upstream:                       # fix and upgrade tasks
  repo: https://github.com/pallets/jinja
  vulnerable_ref: "3.1.2"       # tag or full commit SHA
  fixed_ref: "3.1.3"            # fix tasks only
  license: BSD-3-Clause

advisory:                       # fix and upgrade tasks
  ids: [CVE-2024-22195, GHSA-h5c8-rqwp-cp95]
  cwe: [CWE-79]
  published: 2024-01-11

language: python
tags: [templating, input-validation]

brief:                          # what the agent is told
  detailed: >
    A security report says the xmlattr filter accepts attribute keys that
    contain characters which should never appear in an attribute name.
    Make the filter reject such keys while keeping valid uses working.
  category: >
    There's an input-validation weakness in this project's template filters.
    Find it and fix it.
  blind: >
    Review this project's template filters for security issues and fix any you find.

workdir: /work                  # where the snapshot lives in the environment

checks:                         # all must pass for reward 1
  - name: security
    kind: security              # decides whether the weakness is gone
    cmd: python -m pytest -q /hidden/test_security.py
  - name: regression
    kind: regression            # decides whether normal behaviour still works
    cmd: python -m pytest -q tests/test_filters.py

budget:
  max_steps: 30
  step_timeout_s: 60
  episode_timeout_s: 900
  check_timeout_s: 300

split: public-train             # public-train | public-dev | test (test lives in the private repo)
difficulty: null                # set by calibration (section 7)
authors: [faux16]
```

### Field rules

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | `1` |
| `id` | yes | Matches the folder name |
| `family` | yes | One of the families in section 2 |
| `upstream.*` | fix, upgrade | Refs must be tags or full SHAs, never branch names |
| `advisory.ids` | fix, upgrade | At least one public identifier (CVE, GHSA, OSV) |
| `brief.detailed` | yes | Describes the *symptom*, never the code change |
| `brief.category`, `brief.blind` | yes | Less information than `detailed`, in that order |
| `checks` | yes | At least one `security` check and one `regression` check |
| `budget` | no | Defaults to the values above |
| `split` | yes | Set by maintainers, not contributors |

## 5. Checks

A check is a command run inside the environment **after** the agent submits, with `hidden/` mounted read-only at `/hidden`. It passes if it exits with code 0 within `check_timeout_s`.

- **`security` checks** test for safe behaviour. A security check must also include at least one case of **normal, valid use**, so that deleting or disabling the feature can't pass.
- **`regression` checks** run the project's own tests, or a relevant subset, to confirm nothing broke.
- **Reward = 1** only if every check passes, otherwise 0. Each check's result is still recorded.
- Checks must not need network access.
- Checks must not ship working attack payloads aimed at real systems. They exercise the project's own code with inputs that should be rejected or handled safely.

### Family defaults

| Family | Security check | Regression check |
|---|---|---|
| `fix` | Author-written tests of the safe behaviour | The project's test suite (or a subset) |
| `harden` | A policy scanner (e.g. hadolint, Checkov, kube-linter) with the specific rule IDs the task is about | The config still builds or validates (`docker build`, `kubeconform`, `terraform validate`) |
| `upgrade` | A dependency audit (e.g. `pip-audit`) that must not report the task's advisory | The project's tests |

## 6. Validation

A task is accepted only if CI passes all of these:

| # | Rule | How it's checked |
|---|---|---|
| V1 | **Builds reproducibly** | The environment builds from a clean cache, twice, with identical file trees in `workdir` |
| V2 | **Fails before** | On the untouched environment, at least one `security` check fails |
| V3 | **Passes after** | With the reference solution applied (`fixed_ref`, or `reference/`), every check passes |
| V4 | **Regression holds both ways** | Every `regression` check passes on the untouched environment *and* on the reference solution |
| V5 | **Not trivially gameable** | With the vulnerable code path removed or stubbed out (an automated "delete the feature" mutation where possible, otherwise a manual reviewer step), at least one check fails |
| V6 | **Deterministic** | V2–V4 give the same results across 3 runs |
| V7 | **Offline** | Checks pass and fail the same way with networking disabled |
| V8 | **No leaks** | Nothing from `hidden/` or `reference/` is present in the built environment; upstream git history is not present |
| V9 | **Within budget** | Build < 10 min, all checks < `check_timeout_s` |

## 7. Difficulty calibration

After a task is accepted, a fixed baseline panel of open models runs it n = 8 times at each brief level. Difficulty is set from the `detailed` solve rate:

| Solve rate | Difficulty |
|---|---|
| ≥ 60% | easy |
| 20–60% | medium |
| 1–20% | hard |
| 0% | unsolved (kept, flagged for review) |

Calibration is re-run whenever the baseline panel changes, and the panel is versioned.

## 8. Splits and the private test set

- `public-train` and `public-dev` tasks live in this repo.
- `test` tasks live in a **private** repo with the same format, and are used only for reported results.
- Each release, some test tasks are retired into the public splits and replaced with newer ones, preferring advisories published after the base model's training cutoff.

## 9. Contributor checklist

- [ ] The advisory is public and the upstream fix is released
- [ ] Refs are tags or full SHAs; the license is recorded
- [ ] The briefs describe symptoms, not the patch
- [ ] The security check includes normal-use cases
- [ ] No upstream code is committed; nothing in `hidden/` or `reference/` reaches the image
- [ ] `secwright validate <task-id>` passes locally (V1–V9)
