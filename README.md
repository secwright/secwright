# Secwright

**An open-weight AI model trained to do hands-on security engineering.** It works inside your codebase and infrastructure to find, fix and harden security issues, and it's fast enough to run on your own hardware.

> **Status: Phase 1 (building).** The task format, Docker sandbox and validator work, and the first real-CVE task is in. The agent harness is next. There is no trained model yet.

## What it will be

- **A model.** Open weights, in two sizes: `secwright-mini` for laptops and `secwright-main`, a fast mixture-of-experts model for a single GPU.
- **An agent.** A CLI, an MCP server and an editor extension, all running the model in one tool harness: read, search, edit, run, and security scanners.
- **A training stack.** Open environments built from real, already-patched vulnerabilities, automatic graders, and SFT + RL recipes that run on free Colab at small scale.

The model is trained with reinforcement learning inside the same harness you run it in, so it learns to *do* the work, not just describe it.

## What it will do (v1)

| Job | Example |
|---|---|
| **Fix** | `secwright fix .`: find and patch a vulnerability in your repo, keeping your tests green |
| **Harden** | Tighten Dockerfiles, Kubernetes manifests and Terraform so policy checks pass |
| **Upgrade** | Move off vulnerable dependencies without breaking the build |

Detection engineering and alert triage come in v2.

## Intended use

Secwright is a **defensive** tool. It is built to secure code and infrastructure that you own or are authorised to work on. It doesn't target third-party systems, and its training rewards fixing, not exploiting. See [SECURITY.md](SECURITY.md).

## Docs

- [Plan](docs/PLAN.md): goals, scope, model, roadmap
- [Architecture](docs/ARCHITECTURE.md): components and interfaces
- [Task format](docs/TASK_FORMAT.md): what a task is and how it's validated

## Try it (contributors)

Needs Docker and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run secwright list                                   # show tasks
uv run secwright validate py-jinja2-cve-2024-22195      # build it and check rules V1–V9
uv run secwright validate --all --runs 3 --rebuild      # the full, slow check
```

## Roadmap

In short:

1. **Phase 0:** design (now)
2. **Phase 1:** the agent working with existing open models, plus the first environments and baselines
3. **Phase 2:** `secwright-mini`, the first trained model
4. **Phase 3:** scale up: more environments and `secwright-main`
5. **Phase 4:** security-operations jobs (detections, triage)

## License

[Apache-2.0](LICENSE).
