"""Tool definitions and the registry the harness hands to the model (docs/ARCHITECTURE.md, section 4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..sandbox.base import Sandbox

MAX_OUTPUT_CHARS = 8000


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    ends_episode: bool = False


class ToolError(Exception):
    """Raised by a handler for a problem the model should see and can fix (bad path, no match…)."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema for the arguments
    handler: Callable[[Sandbox, dict], ToolResult]

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def __iter__(self):
        return iter(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [t.openai_schema() for t in self]

    def call(self, sandbox: Sandbox, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(f"unknown tool {name!r}; available: {', '.join(self._tools)}", is_error=True)
        missing = [k for k in tool.parameters.get("required", []) if k not in arguments]
        if missing:
            return ToolResult(f"{name}: missing required argument(s): {', '.join(missing)}", is_error=True)
        try:
            return tool.handler(sandbox, arguments)
        except ToolError as e:
            return ToolResult(f"{name}: {e}", is_error=True)


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Keep the head and the tail; long command output usually matters at both ends."""
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - 2 * half
    return f"{text[:half]}\n… [{omitted} characters omitted] …\n{text[-half:]}"
