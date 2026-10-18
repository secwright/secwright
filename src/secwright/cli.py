"""The `secwright` command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__
from .harness import run_episode
from .models import OpenAICompatClient, ScriptedClient
from .record import append_jsonl
from .sandbox import DockerSandbox, build_image
from .tasks import list_tasks, load_task
from .tasks.validate import format_report, validate


def _cmd_list(args: argparse.Namespace) -> int:
    for t in list_tasks():
        print(f"{t.family:<8} {t.split:<13} {t.id:<40} {t.title}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    tasks = list_tasks() if args.all else [load_task(i) for i in args.task_ids]
    if not tasks:
        print("nothing to validate: pass task ids or --all", file=sys.stderr)
        return 2
    ok = True
    for task in tasks:
        report = validate(
            task, runs=args.runs, rebuild=args.rebuild, log=lambda m: print(f"  · {m}", file=sys.stderr)
        )
        print(format_report(report))
        ok &= report.ok
    return 0 if ok else 1


def _show(kind: str, msg) -> None:
    """Live transcript for `secwright run`."""
    width = 1200
    if kind == "prompt":
        if msg.role == "user":
            print(f"\n── task ──\n{msg.content}\n")
        return
    if kind == "assistant":
        if msg.content.strip():
            print(f"\n🤖 {msg.content.strip()[:width]}")
        for tc in msg.tool_calls:
            args = json.dumps(tc.arguments, ensure_ascii=False)
            print(f"   → {tc.name}({args[:300]}{'…' if len(args) > 300 else ''})")
    elif kind == "tool":
        mark = "✗" if msg.is_error else "←"
        body = msg.content if len(msg.content) <= width else msg.content[:width] + " …"
        print("   " + mark + " " + body.replace("\n", "\n     "))
    elif kind == "nudge":
        print(f"   (nudge) {msg.content}")


def _cmd_run(args: argparse.Namespace) -> int:
    task = load_task(args.task_id)
    if args.oracle:
        # Plumbing check: the upstream fixed version, and an agent that submits straight away.
        if not (task.upstream and task.upstream.fixed_ref):
            print("--oracle needs a fix task with upstream.fixed_ref", file=sys.stderr)
            return 2
        ref, model = task.upstream.fixed_ref, ScriptedClient([], name="oracle")
    else:
        ref = task.upstream.vulnerable_ref if task.upstream else "task"
        api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
        model = OpenAICompatClient(
            args.model,
            base_url=args.base_url,
            api_key=api_key,
            tool_mode=args.tool_mode,
            temperature=args.temperature,
            seed=args.seed,
            max_tokens=args.max_tokens,
        )
    print(f"building {task.id} @ {ref} …", file=sys.stderr)
    built = build_image(task, ref)
    if not built.ok:
        print(built.log_tail, file=sys.stderr)
        return 1
    with DockerSandbox(built.tag, workdir=task.workdir) as sb:
        traj = run_episode(task, model, sb, brief_level=args.brief, on_event=None if args.quiet else _show)
    out = Path(args.out) if args.out else Path("runs") / f"{time.strftime('%Y%m%d')}.jsonl"
    append_jsonl(out, traj)

    print(
        f"\n── result ── stop: {traj.stop_reason} · steps: {traj.steps} · {traj.duration_s}s · "
        f"tokens: {traj.tokens['prompt']}+{traj.tokens['completion']}"
    )
    if traj.error:
        print(f"infra error: {traj.error}")
    changed = [ln[4:] for ln in traj.diff.splitlines() if ln.startswith("+++ ")]
    print(f"files changed: {', '.join(changed) or 'none'}")
    for c in traj.checks:
        print(f"  {'✅' if c['passed'] else '❌'} {c['name']} ({c['kind']}, {c['duration_s']}s)")
    g = traj.grade or {}
    print(f"reward: {g.get('reward')}  flags: {', '.join(g.get('flags', [])) or 'none'}")
    print(f"trajectory → {out}")
    return 0 if g.get("reward") == 1.0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="secwright", description=__doc__)
    p.add_argument("--version", action="version", version=f"secwright {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="list tasks")
    sp.set_defaults(func=_cmd_list)

    sp = sub.add_parser("validate", help="check tasks against rules V1–V9")
    sp.add_argument("task_ids", nargs="*")
    sp.add_argument("--all", action="store_true", help="validate every task")
    sp.add_argument("--runs", type=int, default=1, help="repeat checks to test determinism (V6)")
    sp.add_argument(
        "--rebuild", action="store_true", help="rebuild without cache to test reproducibility (V1)"
    )
    sp.set_defaults(func=_cmd_validate)

    sp = sub.add_parser("run", help="run the agent on one task")
    sp.add_argument("task_id")
    sp.add_argument("--model", default="qwen2.5-coder:1.5b", help="model name on the server")
    sp.add_argument("--base-url", default="http://localhost:11434/v1", help="OpenAI-compatible endpoint")
    sp.add_argument("--api-key-env", help="environment variable that holds the API key, if needed")
    sp.add_argument("--tool-mode", choices=["native", "text"], default="native")
    sp.add_argument("--brief", choices=["detailed", "category", "blind"], default="detailed")
    sp.add_argument("--temperature", type=float, default=0.2)
    sp.add_argument("--max-tokens", type=int, default=2048, help="per model reply")
    sp.add_argument("--seed", type=int)
    sp.add_argument("--out", help="trajectory JSONL file (default runs/<date>.jsonl)")
    sp.add_argument("--oracle", action="store_true", help="plumbing check on the upstream fix, no model")
    sp.add_argument("-q", "--quiet", action="store_true")
    sp.set_defaults(func=_cmd_run)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
