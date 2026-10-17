"""The `secwright` command line."""

from __future__ import annotations

import argparse
import sys

from . import __version__
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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
