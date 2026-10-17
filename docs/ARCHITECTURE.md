# Architecture

Status: **draft, Phase 0.** This spec defines Secwright's components and the interfaces between them, so each can be built and tested on its own. Tasks are specified in [TASK_FORMAT.md](TASK_FORMAT.md).

## 1. Overview

```
            ┌───────────────┐
 task.yaml ─► Task loader   │
            └──────┬────────┘
                   ▼
 ┌──────────┐  ┌───────────┐  tool calls  ┌───────────┐
 │  Model   │◄─┤  Harness  ├─────────────►│  Sandbox  │ Docker | local
 │  client  ├─►│ (agent    │◄─────────────┤           │
 └──────────┘  │  loop)    │  results     └─────┬─────┘
               └─────┬─────┘                    │
                     │ trajectory               │ after submit
                     ▼                          ▼
               ┌───────────┐  checks     ┌───────────┐
               │ Recorder  │◄────────────┤  Grader   │
               └─────┬─────┘  GradeResult└───────────┘
                     ▼
        trajectories.jsonl ──► eval runner ──► results/
                           └─► training (SFT data, GRPO rollouts)
```

**The rule that matters:** the harness, tools and sandbox used for evaluation and training are the same code the product runs. There's no separate "training agent".

## 2. Code layout

```
src/secwright/
├── tasks/        loader, schema, validation (V1–V9)
├── sandbox/      base.py (protocol), docker.py, local.py
├── tools/        registry + core tools + security tools
├── harness/      agent loop, prompts, budgets
├── models/       OpenAI-compatible client, text-tool fallback
├── grading/      grader, GradeResult
├── record/       trajectory schema, JSONL writer
├── evals/        runner, metrics
├── train/        sft_data.py, rollout.py (GRPO interface)
└── cli.py        `secwright …`
```

Python 3.11+, managed with uv. The core package has no dependency on torch; training extras are optional (`secwright[train]`).

## 3. Sandbox

One sandbox = one isolated environment for one episode.

```python
class Sandbox(Protocol):
    def start(self) -> None: ...  # the sandbox is created for one task's image
    def exec(self, cmd: str, timeout_s: int, cwd: str | None = None) -> ExecResult: ...
    def read_file(self, path: str) -> bytes: ...
    def write_file(self, path: str, data: bytes) -> None: ...
    def copy_in(self, src: Path, dest: str) -> None: ...  # root-owned: read-only for the agent
    def diff(self) -> str: ...  # unified diff of workdir vs. the start snapshot
    def close(self) -> None: ...


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
```

### Backends

| | `DockerSandbox` | `LocalSandbox` |
|---|---|---|
| Use | Laptops, servers, CI, the product | Colab and other hosts without Docker |
| Isolation | Container per episode | Fresh copy of the snapshot + its own virtualenv in a temp dir |
| Network | **Off** (`--network none`) | Not enforced: documented as weaker |
| Limits | CPU, memory, PIDs, wall-clock | Wall-clock and output size only |
| User | Non-root | The host user |
| Use for untrusted models or code | Yes | No: only on throwaway machines |

**Snapshot and diff.** At start, the workdir is committed as a fresh git repo with one commit (upstream history removed, see V8). `diff()` returns `git diff` against that commit. That diff is what gets graded, recorded and shown to users.

## 4. Tools

Each tool has a name, a JSON-schema for its arguments, and a handler that runs against the sandbox.

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema
    handler: Callable[[Sandbox, dict], ToolResult]


@dataclass
class ToolResult:
    content: str  # what the model sees (truncated)
    is_error: bool = False
    ends_episode: bool = False
```

### Core tools (all families)

| Tool | Arguments | Behaviour |
|---|---|---|
| `run` | `command` | Runs a shell command in the workdir with the step timeout. Returns exit code + combined output, truncated to 8 KB (head and tail kept) |
| `read_file` | `path`, `start_line?`, `end_line?` | Returns numbered lines, max 400 per call |
| `search` | `pattern`, `path?` | Regex search across the workdir (ripgrep), max 100 matches |
| `edit_file` | `path`, `old`, `new` | Replaces exactly one occurrence of `old`. Errors if there are zero matches or more than one |
| `create_file` | `path`, `content` | Creates a new file; errors if it already exists |
| `submit` | `summary` | Ends the episode; the summary is recorded, not graded |

### Security tools (enabled per family)

| Tool | Families | Wraps |
|---|---|---|
| `scan` | fix, find, triage | Semgrep (CodeQL later) |
| `audit_deps` | upgrade | pip-audit / npm audit / osv-scanner |
| `check_config` | harden | hadolint, Checkov, kube-linter |

Security tools run in the same sandbox and are pre-installed in task images. They're helpers for the agent. The grader never trusts their output from inside the episode; checks run separately (section 6).

**Tool errors** (bad arguments, no match for `edit_file`) go back to the model as `is_error` results. They don't end the episode.

## 5. Harness (agent loop)

```python
class ModelClient(Protocol):
    def chat(self, messages: list[Message], tools: list[Tool]) -> ModelResponse: ...


def run_episode(
    task: Task, model: ModelClient, sandbox: Sandbox, brief_level: str = "detailed", seed: int | None = None
) -> Trajectory: ...
```

Loop:

1. Start the sandbox. Build the system prompt (role, rules, tool list) and the user message (the task brief).
2. Call the model. If it returns tool calls, run each one and append the results.
3. Stop when the model calls `submit`, or when a budget runs out: `max_steps`, `episode_timeout_s`, or a token limit.
4. Hand off to the grader (section 6), then record the trajectory.

### Model client

- Talks to any **OpenAI-compatible** chat endpoint: vLLM, Ollama, llama.cpp server, hosted APIs.
- Uses native tool calls when the model supports them. Otherwise it falls back to a **text tool format** (a fenced JSON block per call) that the client parses. The fallback is recorded in the trajectory.
- Sampling settings (temperature, top_p, max tokens, seed) are part of the run config and are recorded.

### Prompts

Prompts are versioned files in `harness/prompts/`. Changing one bumps the harness version (section 9).

## 6. Grader

```python
@dataclass
class CheckResult:
    name: str
    kind: Literal["security", "regression"]
    passed: bool
    exit_code: int
    duration_s: float
    output_tail: str  # last 4 KB, for debugging


@dataclass
class GradeResult:
    reward: float  # 1.0 if every check passed, else 0.0
    checks: list[CheckResult]
    flags: list[str]  # e.g. "modified_test_files", "empty_diff", "infra_error"
```

Steps after `submit` (or budget exhaustion):

1. Record `sandbox.diff()`.
2. Raise **flags**: the diff touches test files, the diff is empty, the diff removes more than N lines, the diff touches files outside the workdir.
3. `copy_in(hidden/, "/hidden", read_only=True)`. This is the first time hidden files enter the environment.
4. Run every check with its timeout, from a clean shell the agent never controlled.
5. Compute the reward. Flags don't change the reward automatically. They feed audits, and the reward rules can be tightened per flag after an audit.

**Infra failures** (image pull failed, sandbox crashed) produce the flag `infra_error`. Those episodes are excluded from metrics and retried, never scored 0.

## 7. Trajectory record

One JSON object per episode, appended to `trajectories.jsonl`:

```json
{
  "schema_version": 1,
  "episode_id": "uuid",
  "task_id": "py-jinja2-cve-2024-22195",
  "task_set_version": "0.1.0",
  "harness_version": "0.1.0",
  "model": {"name": "qwen2.5-coder-7b-instruct", "endpoint": "vllm", "sampling": {"temperature": 0.7, "top_p": 0.95, "seed": 3}},
  "brief_level": "detailed",
  "messages": [
    {"role": "system", "content": "…"},
    {"role": "user", "content": "…"},
    {"role": "assistant", "content": "…", "tool_calls": [{"id": "c1", "name": "search", "arguments": {"pattern": "xmlattr"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "…", "is_error": false}
  ],
  "stop_reason": "submit",
  "steps": 14,
  "tokens": {"prompt": 48210, "completion": 3120},
  "duration_s": 212.4,
  "diff": "--- a/src/jinja2/filters.py …",
  "grade": {"reward": 1.0, "checks": [ … ], "flags": []}
}
```

Training reads this format directly, so changes to it are versioned and backwards-compatible within a major version.

## 8. Evals and training interfaces

### Eval runner

`secwright eval --tasks <split|glob> --model <config> --samples n --brief <level> --concurrency c`

Metrics per task, family, and overall:

- **pass@1:** mean reward over the n samples.
- **pass@k:** the unbiased estimator `1 - C(n-c, k) / C(n, k)`, where c is the number of successful samples.
- Mean steps, tokens, wall-clock time, and **cost per solved task** (tokens × the configured price).
- Count of `infra_error` episodes (excluded from the above).

Results are written as JSON to `results/<run-id>.json`, including every setting needed to reproduce the run.

### SFT data

`train/sft_data.py` turns successful trajectories into chat-format training examples:

- Assistant turns (text + tool calls) are **trained on**.
- System, user and tool-result turns are **masked out** of the loss.
- Filters: reward = 1, no flags, below a step limit. Optional de-duplication by diff.

### GRPO rollouts

```python
def rollout(task: Task, policy: ModelClient, group_size: int, brief_level: str) -> list[Trajectory]: ...
```

It returns `group_size` graded trajectories for one task. The trainer computes group-relative advantages from their rewards and masks tool-result tokens. The trainer itself (TRL, verl, or our own) sits behind this interface, so the environment side doesn't depend on any training framework.

## 9. Versioning

| Thing | Version | Bumped when |
|---|---|---|
| Package | semver | Any release |
| Harness | `harness_version` | Prompts, tools, budgets or the loop change behaviour |
| Task set | `task_set_version` | Tasks are added, changed or re-split |
| Schemas | `schema_version` | `task.yaml` or the trajectory format changes |

Every result and trajectory records the harness and task-set versions, and results are only compared across matching versions.

## 10. CLI (Phase 1)

| Command | Does |
|---|---|
| `secwright validate <task-id>…` | Runs V1–V9 on tasks |
| `secwright run <task-id> --model …` | One episode, streaming the transcript |
| `secwright eval …` | Batch runs + metrics (section 8) |
| `secwright fix [path] --model …` | Product mode: run the agent on your own repo in a sandbox, then show the diff for you to apply |

## 11. Security of the system itself

- Model-generated commands run only inside a sandbox. In Docker mode: no network, non-root, resource-limited, and only the workdir writable.
- Hidden check files enter the sandbox only after the episode ends, read-only.
- In product mode, Secwright never applies changes to the user's repo without approval, and never pushes or merges by itself.
- `LocalSandbox` is documented as unsafe for untrusted code and is meant for disposable machines such as Colab.
- Sandbox escapes and grader bypasses are in scope for [SECURITY.md](../SECURITY.md) reports.
