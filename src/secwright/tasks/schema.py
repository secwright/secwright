"""The task.yaml schema (docs/TASK_FORMAT.md, section 4)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Family = Literal["fix", "harden", "upgrade"]
Split = Literal["public-train", "public-dev", "test"]
BriefLevel = Literal["detailed", "category", "blind"]

_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_BRANCHY = {"main", "master", "develop", "dev", "trunk", "HEAD"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Upstream(_Strict):
    repo: str
    vulnerable_ref: str
    fixed_ref: str | None = None
    license: str

    @field_validator("vulnerable_ref", "fixed_ref")
    @classmethod
    def _pinned(cls, v: str | None) -> str | None:
        # Refs must be tags or full SHAs, never branch names (they move).
        if v is None:
            return v
        if v in _BRANCHY or (len(v) < 40 and re.fullmatch(r"[0-9a-f]{7,39}", v)):
            raise ValueError(f"ref {v!r} must be a tag or a full 40-character commit SHA")
        return v

    @property
    def vulnerable_is_sha(self) -> bool:
        return bool(_SHA_RE.match(self.vulnerable_ref))


class Advisory(_Strict):
    ids: list[str] = Field(min_length=1)
    cwe: list[str] = []
    published: date | None = None


class Brief(_Strict):
    detailed: str
    category: str
    blind: str

    def at(self, level: BriefLevel) -> str:
        return getattr(self, level).strip()


class Check(_Strict):
    name: str
    kind: Literal["security", "regression"]
    cmd: str


class Budget(_Strict):
    max_steps: int = 30
    step_timeout_s: int = 60
    episode_timeout_s: int = 900
    check_timeout_s: int = 300


class Task(_Strict):
    schema_version: Literal[1]
    id: str
    family: Family
    title: str
    upstream: Upstream | None = None
    advisory: Advisory | None = None
    language: str
    tags: list[str] = []
    brief: Brief
    workdir: str = "/work"
    checks: list[Check] = Field(min_length=2)
    budget: Budget = Budget()
    split: Split
    difficulty: Literal["easy", "medium", "hard", "unsolved"] | None = None
    authors: list[str] = Field(min_length=1)

    # Set by the loader, not read from YAML.
    path: Path | None = Field(default=None, exclude=True)

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("id must be lowercase words joined by '-', e.g. py-jinja2-cve-2024-22195")
        return v

    @model_validator(mode="after")
    def _family_rules(self) -> Task:
        kinds = {c.kind for c in self.checks}
        if kinds != {"security", "regression"}:
            raise ValueError("checks need at least one 'security' and one 'regression' check")
        if len({c.name for c in self.checks}) != len(self.checks):
            raise ValueError("check names must be unique")
        if self.family in ("fix", "upgrade"):
            if self.upstream is None or self.advisory is None:
                raise ValueError(f"{self.family} tasks need 'upstream' and 'advisory'")
        if self.family == "fix" and self.upstream and not self.upstream.fixed_ref:
            raise ValueError("fix tasks need upstream.fixed_ref (the reference solution)")
        return self

    # Convenience paths inside the task folder.
    @property
    def environment_dir(self) -> Path:
        assert self.path is not None
        return self.path / "environment"

    @property
    def hidden_dir(self) -> Path:
        assert self.path is not None
        return self.path / "hidden"

    @property
    def reference_dir(self) -> Path:
        assert self.path is not None
        return self.path / "reference"
