# Secwright: project plan

Status: **draft, Phase 0.** This is a living document; changes go through pull requests.

## 1. Goal

Build an open-weight AI model that does hands-on, defensive security engineering. It works as an agent inside a user's own code and infrastructure, and it's fast and small enough to run on the user's own hardware.

Three things ship together:

1. **Model:** open weights, trained for agentic security work.
2. **Agent and harness:** the tools and loop the model works in. The same harness is used for training and in the product.
3. **Training stack:** environments, graders and recipes, so anyone can reproduce and extend the model.

### Non-goals

- Tooling for attacking live or third-party systems.
- Discovering undisclosed vulnerabilities in other people's software.
- Exploit payloads beyond what a test needs to check safe behaviour.

## 2. Principles

1. **Train where you deploy.** The model learns inside the exact harness users run.
2. **Verifiable rewards only.** Every task is checked automatically, and every task is validated both ways before it ships: the check fails on the vulnerable version and passes on the maintainers' fix.
3. **Never redistribute upstream code.** Tasks reference an upstream repo and commit, and snapshots are built from there.
4. **Reproducible.** Pinned dependencies, deterministic builds, published evaluation settings.
5. **Cheap first.** Everything works on a laptop plus free Colab at small scale. Bigger compute is optional.
6. **Defensive by design.** Graders reward fixes, tests check safe behaviour, and every action is sandboxed.

## 3. Users and jobs

| User | Job | Version |
|---|---|---|
| Developer | Find and fix vulnerabilities in my repo; review my pull request for security issues | v1 |
| Platform / DevOps | Harden Dockerfiles, Kubernetes manifests and Terraform | v1 |
| Developer / AppSec | Upgrade vulnerable dependencies without breaking the build | v1 |
| AppSec engineer | Go through scanner findings: dismiss false positives, fix real ones | v1.x |
| Detection engineer | Write and tune Sigma rules | v2 |
| SOC analyst | Triage an alert using logs and context | v2 |

## 4. Architecture

```
public advisories ─► task builder ─► validator ─► task registry (public + private held-out)
                                                       │
model (OpenAI-compatible) ◄── harness ──► sandbox (Docker | folder mode)
                                 │ trajectory
                                 ▼
                              grader ─► reward + metrics
                                 │
                   ┌─────────────┴─────────────┐
                   ▼                           ▼
             eval runner                 training recipes
       (pass@1, pass@k, cost)        (SFT data, multi-turn GRPO)
```

### 4.1 Environments

| Family | Episode | Reward |
|---|---|---|
| **Fix** | Repo at a version with a public, already-patched vulnerability, plus an issue description | Hidden security tests pass and the project's own tests still pass |
| **Find** | Same repos, no hint | Correct file, function and weakness category |
| **Triage** | Repo plus scanner output | Correct true/false-positive verdicts, plus fixes for the true ones |
| **Harden** | A misconfigured Dockerfile, manifest or Terraform module | The policy checker passes and the config still validates |
| **Upgrade** | A project with a vulnerable dependency | The dependency audit is clean and the tests pass |
| **Detect** (v2) | Attack and benign logs | The rule fires on attacks and stays quiet on benign activity |
| **Alert triage** (v2) | An alert plus context | The verdict matches the label |

**Splits:** `public-train`, `public-dev`, and a **private** held-out `test` set (about 20%) that is used only for reported results. Tasks are refreshed every release, favouring advisories published after the base model's training cutoff.

### 4.2 Harness

- Works with any OpenAI-compatible endpoint (vLLM, Ollama, hosted APIs), using native tool calls with a text fallback.
- **Core tools:** `run`, `read_file`, `edit_file` (exact, unique snippet replacement), `search`, `submit`.
- **Security tools:** `scan` (SAST), `audit_deps`, `check_config`; in v2, `query_logs` and `compile_rule`.
- Step, time and token budgets; output truncation; full trajectory logging (JSONL).
- **Modes:** *interactive* (the user approves edits) and *autonomous* (CI or a pull-request bot that only proposes changes).

### 4.3 Grader and anti-gaming

- **Reward:** 1 if the security tests and the regression tests both pass, otherwise 0. Partial results are logged, not trained on.
- **Defences:**
  - Tests are copied in only after `submit`.
  - The grader runs its own commands.
  - Security tests also check normal behaviour, so deleting the feature fails.
  - Several inputs per task.
  - Changes to test files are flagged.
- A random sample of passing trajectories is audited by hand each release. Reward hacks we find are logged publicly along with their fixes.

## 5. Model

| Model | Size | Purpose |
|---|---|---|
| `secwright-mini` | 1.5–7B dense | Laptops; trainable on free or cheap compute; first release |
| `secwright-main` | ~30B mixture-of-experts, ~3B active | Fast agent turns on a single GPU once quantised |

Base: a permissively licensed open model family (default: Qwen3).

**Training stages:**

1. **(Optional) continued pretraining** on security text: public advisories, weakness documentation, secure-coding guides, fix commits.
2. **SFT on agent trajectories** recorded in the harness: rejection-sampled successes, plus outputs from a teacher model whose terms allow it. The loss is computed only on the model's own turns.
3. **Multi-turn GRPO** across all task families together.
4. **Safety tuning:** decline requests to attack third-party systems, measured with public misuse evaluations.
5. **Speed:** quantisation, speculative decoding, vLLM serving settings.

## 6. Evaluation

- **Per family**, on the private test set:
  - pass@1 (averaged over several samples) and pass@k
  - steps, tokens and wall-clock time per task
  - cost per solved task
- **Public benchmarks** where relevant, including a general coding benchmark to check we haven't lost general ability.
- **Comparisons:** the base model, other open models of similar size, and a frontier API model as a reference.
- **Fixed, published settings:** temperature, step budget, prompt level, harness version.

## 7. Compute

| Stage | Compute |
|---|---|
| Harness, environments, baselines with existing open models | Laptop + free Colab |
| `secwright-mini` SFT + RL (1.5–3B) | Colab Pro or a single rented GPU for days |
| `secwright-mini` at 7B | One 40–80 GB GPU for days |
| `secwright-main` SFT + RL | Multi-GPU nodes for weeks, plus many parallel sandboxes. This needs sponsorship or cloud credits |

These are estimates, to be refined with real throughput numbers in Phase 2.

## 8. Roadmap

| Phase | Ships | Done when |
|---|---|---|
| **0: Design** | This plan, architecture docs, task-format spec, repo setup | Spec agreed |
| **1: Agent v0** | CLI agent + harness on existing open models, **Fix** family (~20 tasks), baselines, CI task validation | `secwright fix` works on real repos with published baseline scores |
| **2: mini v0.1** | Fix + Harden + Upgrade (~100 tasks), SFT + RL recipes, `secwright-mini` weights + model card | mini beats its base and same-size open models on the private test set |
| **3: Scale** | Find + Triage families, 300+ tasks, MCP server, editor extension, `secwright-main` | main is competitive with much larger models and fast on one GPU |
| **4: SecOps** | Detect + Alert-triage families, log and SIEM tools, main v2 | Comparable results on detection and triage |

## 9. Open-source release

- **Open:** code, harness, agent, training recipes, public environments, trajectory datasets, model weights.
- **Private:** the held-out test set, to keep reported results honest.
- **Licenses:** Apache-2.0 for code and weights (subject to the base model's license). Task metadata under CC-BY-4.0. Upstream projects keep their own licenses and are never redistributed.
- **Responsible release:** model cards covering intended use, limits and misuse-evaluation results; a [SECURITY.md](../SECURITY.md); and a staged rollout (mini before main).

## 10. Risks

| Risk | Mitigation |
|---|---|
| Not enough compute for `main` | Ship `mini` first and use its results to secure credits and sponsors |
| General models improve quickly | Focus on what they can't offer: open weights, runs on your own servers, speed, low cost per task |
| Misuse of open weights | Defensive scope, safety tuning, misuse evaluations, clear model cards, staged release |
| Reward hacking, contamination | Hidden tests, normal-behaviour checks, trajectory audits, private held-out set |
| Licensing | Permissive base model; reference upstream code instead of copying it; only teachers whose terms allow it |
| Upstream breakage | Pinned dependencies, prebuilt images, CI re-validation every release |
| Maintainer burnout | Small, frequent releases; early co-maintainers; good first issues for contributors |
