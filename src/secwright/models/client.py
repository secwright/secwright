"""Model clients (docs/ARCHITECTURE.md, section 5)."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    parse_error: str | None = None  # set when the model sent arguments we couldn't parse


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    is_error: bool = False

    def to_record(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [asdict(tc) for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
            d["is_error"] = self.is_error
        return d


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ModelResponse:
    message: Message
    usage: Usage
    finish_reason: str | None = None


class ModelClient(Protocol):
    name: str
    tool_mode: str

    def chat(self, messages: list[Message], tools: list[dict]) -> ModelResponse: ...

    def describe(self) -> dict: ...


# --- text tool format (for models without native tool calling) ---------------------------

TEXT_TOOL_INSTRUCTIONS = """
## How to call tools

Call a tool by replying with a fenced block tagged `tool` containing one JSON object:

```tool
{"name": "read_file", "arguments": {"path": "src/app.py"}}
```

You may include several blocks in one reply. Tool results come back in the next message.

Available tools (JSON schemas):
{schemas}
"""

_TOOL_BLOCK = re.compile(r"```tool\s*\n(.*?)\n```", re.S)


def parse_text_tool_calls(text: str) -> list[ToolCall]:
    calls = []
    for raw in _TOOL_BLOCK.findall(text):
        try:
            obj = json.loads(raw)
            calls.append(
                ToolCall(f"t{uuid.uuid4().hex[:8]}", str(obj["name"]), dict(obj.get("arguments") or {}))
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            calls.append(
                ToolCall(f"t{uuid.uuid4().hex[:8]}", "?", {}, parse_error=f"invalid tool block: {e}")
            )
    return calls


# --- OpenAI-compatible HTTP client --------------------------------------------------------


class OpenAICompatClient:
    """Chat Completions over HTTP: vLLM, Ollama, llama.cpp server, or hosted APIs."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434/v1",
        api_key: str | None = None,
        tool_mode: Literal["native", "text"] = "native",
        temperature: float = 0.2,
        top_p: float = 0.95,
        max_tokens: int = 2048,
        seed: int | None = None,
        timeout_s: float = 300,
    ):
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.tool_mode = tool_mode
        self.sampling = {"temperature": temperature, "top_p": top_p, "max_tokens": max_tokens, "seed": seed}
        key = api_key or os.environ.get("SECWRIGHT_API_KEY") or "none"
        self._http = httpx.Client(timeout=timeout_s, headers={"Authorization": f"Bearer {key}"})

    def describe(self) -> dict:
        return {
            "name": self.name,
            "endpoint": self.base_url,
            "tool_mode": self.tool_mode,
            "sampling": self.sampling,
        }

    def chat(self, messages: list[Message], tools: list[dict]) -> ModelResponse:
        payload: dict = {
            "model": self.name,
            "messages": list(self._wire(messages, tools)),
            **{k: v for k, v in self.sampling.items() if v is not None},
        }
        if self.tool_mode == "native" and tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        r = self._http.post(f"{self.base_url}/chat/completions", json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"model server returned {r.status_code}: {r.text[:500]}")
        data = r.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        if self.tool_mode == "native":
            calls = [self._parse_native(tc) for tc in msg.get("tool_calls") or []]
        else:
            calls = parse_text_tool_calls(content)
        u = data.get("usage") or {}
        return ModelResponse(
            Message("assistant", content, calls),
            Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)),
            choice.get("finish_reason"),
        )

    @staticmethod
    def _parse_native(tc: dict) -> ToolCall:
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = raw if isinstance(raw, dict) else json.loads(raw)
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
            return ToolCall(tc.get("id") or f"c{uuid.uuid4().hex[:8]}", fn.get("name", "?"), args)
        except (json.JSONDecodeError, ValueError) as e:
            return ToolCall(
                tc.get("id") or f"c{uuid.uuid4().hex[:8]}", fn.get("name", "?"), {}, f"bad arguments: {e}"
            )

    def _wire(self, messages: list[Message], tools: list[dict]) -> Iterable[dict]:
        """Convert our messages to the wire format for the chosen tool mode."""
        for m in messages:
            if self.tool_mode == "text":
                if m.role == "system" and tools:
                    schemas = json.dumps([t["function"] for t in tools], indent=1)
                    yield {
                        "role": "system",
                        "content": m.content + TEXT_TOOL_INSTRUCTIONS.replace("{schemas}", schemas),
                    }
                elif m.role == "tool":
                    yield {
                        "role": "user",
                        "content": f"[tool result{' (error)' if m.is_error else ''}]\n{m.content}",
                    }
                else:
                    yield {"role": m.role, "content": m.content}
                continue
            if m.role == "assistant" and m.tool_calls:
                yield {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ],
                }
            elif m.role == "tool":
                yield {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
            else:
                yield {"role": m.role, "content": m.content}


# --- scripted client (tests, oracle runs) -------------------------------------------------


class ScriptedClient:
    """Replays a fixed list of tool calls. Useful for tests and for checking the plumbing."""

    tool_mode = "native"

    def __init__(self, steps: list[list[tuple[str, dict]]], name: str = "scripted"):
        self.name = name
        self._steps = list(steps)

    def describe(self) -> dict:
        return {"name": self.name, "endpoint": "scripted", "tool_mode": "native", "sampling": {}}

    def chat(self, messages: list[Message], tools: list[dict]) -> ModelResponse:
        calls = self._steps.pop(0) if self._steps else [("submit", {"summary": "script finished"})]
        return ModelResponse(
            Message("assistant", "", [ToolCall(f"s{uuid.uuid4().hex[:6]}", n, a) for n, a in calls]), Usage()
        )
