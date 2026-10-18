"""The agent loop: one episode of one task (docs/ARCHITECTURE.md, section 5)."""

from __future__ import annotations

import time
from collections.abc import Callable
from importlib import resources

from .. import __version__
from ..grading.checks import copy_hidden, run_checks
from ..grading.grader import grade
from ..models.client import Message, ModelClient
from ..record.trajectory import Trajectory
from ..sandbox.base import Sandbox
from ..tasks.schema import BriefLevel, Task
from ..tools import ToolRegistry, core_tools

HARNESS_VERSION = "0.1.0"
TASK_SET_VERSION = "0.0.1"
PROMPT_FILE = "system_v1.md"
MAX_IDLE_TURNS = 3  # consecutive replies with no tool call before we give up
NUDGE = "Use one of the tools to continue, or call `submit` if you are done."


def system_prompt(task: Task) -> str:
    text = resources.files("secwright.harness").joinpath("prompts", PROMPT_FILE).read_text()
    return text.replace("{workdir}", task.workdir).replace("{max_steps}", str(task.budget.max_steps))


def run_episode(
    task: Task,
    model: ModelClient,
    sandbox: Sandbox,
    brief_level: BriefLevel = "detailed",
    tools: ToolRegistry | None = None,
    max_total_tokens: int = 400_000,
    on_event: Callable[[str, Message], None] | None = None,
    run_checks_after: bool = True,
) -> Trajectory:
    """Run the agent until it submits or a budget runs out, then run the hidden checks.

    The sandbox must already be started. Turning check results into a reward is the grader's job.
    """
    tools = tools or core_tools(task.budget.step_timeout_s)
    schemas = tools.schemas()
    traj = Trajectory(task.id, TASK_SET_VERSION, HARNESS_VERSION, model.describe(), brief_level)
    traj.model["secwright_version"] = __version__
    messages = [Message("system", system_prompt(task)), Message("user", task.brief.at(brief_level))]
    emit = on_event or (lambda kind, msg: None)
    for m in messages:
        emit("prompt", m)

    t0, idle, steps = time.monotonic(), 0, 0
    stop = ""
    try:
        while not stop:
            if steps >= task.budget.max_steps:
                stop = "max_steps"
                break
            if time.monotonic() - t0 > task.budget.episode_timeout_s:
                stop = "episode_timeout"
                break
            if traj.tokens["prompt"] + traj.tokens["completion"] > max_total_tokens:
                stop = "token_budget"
                break

            resp = model.chat(messages, schemas)
            traj.tokens["prompt"] += resp.usage.prompt_tokens
            traj.tokens["completion"] += resp.usage.completion_tokens
            messages.append(resp.message)
            emit("assistant", resp.message)

            if not resp.message.tool_calls:
                idle += 1
                steps += 1
                if idle >= MAX_IDLE_TURNS:
                    stop = "no_action"
                    break
                messages.append(Message("user", NUDGE))
                emit("nudge", messages[-1])
                continue

            idle = 0
            for call in resp.message.tool_calls:
                steps += 1
                if call.parse_error:
                    result_msg = Message("tool", call.parse_error, tool_call_id=call.id, is_error=True)
                else:
                    result = tools.call(sandbox, call.name, call.arguments)
                    result_msg = Message(
                        "tool", result.content, tool_call_id=call.id, is_error=result.is_error
                    )
                    if result.ends_episode:
                        stop = "submit"
                messages.append(result_msg)
                emit("tool", result_msg)
                if stop or steps >= task.budget.max_steps:
                    break

        traj.diff = sandbox.diff()
        if run_checks_after:
            copy_hidden(task, sandbox)
            traj.checks = [c.to_dict() for c in run_checks(task, sandbox)]
    except Exception as e:  # infrastructure failure: recorded, never scored as a model failure
        traj.error = f"{type(e).__name__}: {e}"
        stop = stop or "infra_error"

    traj.stop_reason = stop
    traj.steps = steps
    traj.duration_s = round(time.monotonic() - t0, 2)
    traj.messages = [m.to_record() for m in messages]
    if run_checks_after:
        traj.grade = grade(traj.checks, traj.diff, traj.stop_reason, traj.error).to_dict()
    return traj
