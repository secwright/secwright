from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from secwright.tasks import Task, list_tasks

ROOT = Path(__file__).resolve().parents[1] / "tasks"


def test_all_tasks_load():
    tasks = list_tasks(ROOT)
    assert tasks, "expected at least one task"
    assert len({t.id for t in tasks}) == len(tasks)


def test_hidden_files_never_copied_by_dockerfiles():
    for t in list_tasks(ROOT):
        text = (t.environment_dir / "Dockerfile").read_text()
        assert "hidden" not in text and "reference" not in text, t.id


def _base() -> dict:
    return yaml.safe_load((ROOT / "fix/py-jinja2-cve-2024-22195/task.yaml").read_text())


def test_branch_refs_rejected():
    data = _base()
    data["upstream"]["vulnerable_ref"] = "main"
    with pytest.raises(ValidationError):
        Task.model_validate(data)


def test_short_sha_rejected():
    data = _base()
    data["upstream"]["fixed_ref"] = "abc1234"
    with pytest.raises(ValidationError):
        Task.model_validate(data)


def test_needs_security_and_regression_checks():
    data = _base()
    data["checks"] = [c for c in data["checks"] if c["kind"] == "security"] * 2
    with pytest.raises(ValidationError):
        Task.model_validate(data)


def test_fix_task_needs_fixed_ref():
    data = _base()
    del data["upstream"]["fixed_ref"]
    with pytest.raises(ValidationError):
        Task.model_validate(data)


def test_unknown_fields_rejected():
    data = _base()
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        Task.model_validate(data)
