from pathlib import Path

import pytest

from secwright.harness import run_episode
from secwright.models import ScriptedClient, parse_text_tool_calls
from secwright.sandbox import DockerSandbox, build_image
from secwright.tasks import load_task

from .conftest import docker_available

ROOT = Path(__file__).resolve().parents[1] / "tasks"
TASK = "py-jinja2-cve-2024-22195"


def test_text_tool_blocks_parse():
    text = 'Let me look.\n```tool\n{"name": "read_file", "arguments": {"path": "a.py"}}\n```\n'
    text += '```tool\n{"name": "submit"\n```'
    calls = parse_text_tool_calls(text)
    assert calls[0].name == "read_file" and calls[0].arguments == {"path": "a.py"}
    assert calls[1].parse_error


def test_episode_stops_at_max_steps(sandbox):
    task = load_task(TASK, ROOT)
    task = task.model_copy(update={"budget": task.budget.model_copy(update={"max_steps": 3})})
    model = ScriptedClient([[("read_file", {"path": "pkg/app.py"})]] * 10)
    traj = run_episode(task, model, sandbox, run_checks_after=False)
    assert traj.stop_reason == "max_steps" and traj.steps == 3


def test_idle_model_gives_up(sandbox):
    class Silent(ScriptedClient):
        def chat(self, messages, tools):
            r = super().chat(messages, tools)
            r.message.tool_calls = []
            r.message.content = "thinking…"
            return r

    traj = run_episode(load_task(TASK, ROOT), Silent([]), sandbox, run_checks_after=False)
    assert traj.stop_reason == "no_action"


# The fix a competent agent would make, applied through the real tools in a real container.
OLD = """    rv = " ".join(
        f'{escape(key)}="{escape(value)}"'
        for key, value in d.items()
        if value is not None and not isinstance(value, Undefined)
    )"""
NEW = """    items = []
    for key, value in d.items():
        if value is None or isinstance(value, Undefined):
            continue
        if any(c.isspace() for c in key):
            raise ValueError(f"Invalid character in attribute name: {key!r}")
        items.append(f'{escape(key)}="{escape(value)}"')
    rv = " ".join(items)"""


@pytest.mark.docker
@pytest.mark.skipif(not docker_available(), reason="needs Docker")
def test_scripted_fix_end_to_end():
    task = load_task(TASK, ROOT)
    built = build_image(task, task.upstream.vulnerable_ref)
    assert built.ok, built.log_tail
    model = ScriptedClient(
        [
            [("search", {"pattern": "def do_xmlattr"})],
            [("edit_file", {"path": "src/jinja2/filters.py", "old": OLD, "new": NEW})],
            [("submit", {"summary": "reject whitespace in xmlattr keys"})],
        ]
    )
    with DockerSandbox(built.tag, workdir=task.workdir) as sb:
        traj = run_episode(task, model, sb)
    assert traj.stop_reason == "submit", traj.error
    assert "+++ b/src/jinja2/filters.py" in traj.diff
    assert {c["name"]: c["passed"] for c in traj.checks} == {"security": True, "regression": True}
