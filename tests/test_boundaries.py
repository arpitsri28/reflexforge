import json
from unittest.mock import MagicMock

import pytest
from conftest import ROOT
from pydantic import ValidationError

from reflexforge.evaluation.evaluator import Evaluator, Patch, make_patch
from reflexforge.sandbox.manager import DockerSandbox, InvalidPatchError, SandboxError
from reflexforge.schema import Task
from reflexforge.storage.database import Database
from reflexforge.storage.traces import Trace
from reflexforge.tasks import load_tasks
from reflexforge.worker.tools import WorkerTools


def test_configuration_strict_and_content_addressed(config):
    other = config.model_copy(deep=True)
    assert config.version == other.version
    other.skills["debugging"] += "more"
    assert config.version != other.version
    with pytest.raises(ValidationError):
        config.params.model_validate({"max_steps": 3, "security": "disabled"})


def test_expanded_task_bank_has_three_separate_splits():
    tasks = load_tasks(ROOT / "tasks")
    assert len(tasks) == 38
    assert {t.split for t, _ in tasks} == {"train", "dev", "test"}
    raw = tasks[0][0].model_dump()
    raw["repository"] = "../escape"
    with pytest.raises(ValidationError):
        Task.model_validate(raw)


def test_staging_cannot_traverse():
    client = MagicMock()
    with DockerSandbox("image", 10, 5, client) as box:
        with pytest.raises(ValueError):
            box.upload({"../secret": "bad"})
    client.api.exec_create.assert_not_called()


def test_patch_allowlist_and_forged_patch():
    with pytest.raises(ValueError):
        make_patch({"source.py": "old"}, {"hidden.py": "bad"}, ["source.py"])
    patch = make_patch({"source.py": "old\n"}, {"source.py": "new\n"}, ["source.py"])
    assert "-old" in patch.diff and "+new" in patch.diff
    factory = MagicMock()
    task, _ = load_tasks(ROOT / "tasks")[0]
    with pytest.raises(ValueError):
        Evaluator(factory).evaluate(task, {"solution.py": ""}, Patch({"hidden.py": ""}, ""), "")
    factory.assert_not_called()


def test_file_tools_reject_traversal_and_unapproved_edit(config):
    box = MagicMock()
    tools = WorkerTools(box, config, ["solution.py"])
    for path in ["../secret", "/etc/passwd"]:
        with pytest.raises(ValueError):
            tools.call("read_file", {"path": path})
    with pytest.raises(ValueError):
        tools.call("edit_file", {"path": "hidden.py", "content": ""})
    with pytest.raises(ValidationError):
        tools.call("run_shell", {"command": "true", "host": True})
    box.execute.assert_not_called()
    assert len(tools.definitions()) == 7


def test_sandbox_security_and_exception_cleanup():
    client = MagicMock()
    container = client.containers.create.return_value
    with pytest.raises(RuntimeError):
        with DockerSandbox("image", 10, 5, client):
            raise RuntimeError("failure")
    args = client.containers.create.call_args.kwargs
    assert args["network_disabled"] and args["read_only"]
    assert args["user"] == "1000:1000"
    assert args["cap_drop"] == ["ALL"]
    assert "volumes" not in args
    assert args["pids_limit"] == 64
    container.remove.assert_called_once_with(force=True, v=True)


def test_snapshot_error_is_invalid_patch():
    client = MagicMock()
    client.api.exec_start.return_value = [b"source must be a bounded regular file"]
    client.api.exec_inspect.return_value = {"ExitCode": 1}
    with DockerSandbox("image", 10, 5, client) as box:
        with pytest.raises(InvalidPatchError):
            box.read("solution.py")


def test_output_overflow_terminates_container():
    client = MagicMock()
    client.api.exec_start.return_value = [b"x" * 64001]
    with DockerSandbox("image", 10, 5, client) as box:
        with pytest.raises(SandboxError):
            box.execute(["echo"])
        client.containers.create.return_value.kill.assert_called_once()


def test_trace_redaction_and_synthetic_exclusion(tmp_path, monkeypatch):
    from reflexforge.schema import RunResult

    monkeypatch.setenv("OPENAI_API_KEY", "my-secret-credential")
    trace = Trace(tmp_path / "trace.jsonl", "id")
    trace.event("output", {"text": "my-secret-credential and sk-proj-test-key"})
    assert "my-secret-credential" not in trace.path.read_text()
    assert "sk-proj-test-key" not in trace.path.read_text()
    json.loads(trace.path.read_text())
    db = Database(tmp_path / "runs.sqlite3")
    db.start("id", "task_001", "train", True)
    result = RunResult(
        run_id="id",
        task_id="task_001",
        config_version="v",
        model="none",
        synthetic=True,
        termination="synthetic_plan_only",
        patch="my-secret-credential",
    )
    db.finish(result, trace)
    assert db.results() == []
    assert db.results(include_synthetic=True)[0]["patch"] == "[REDACTED]"


def test_startup_failure_removes_created_container():
    client = MagicMock()
    container = client.containers.create.return_value
    container.start.side_effect = RuntimeError("failed to start")
    with pytest.raises(SandboxError, match="startup failed"):
        with DockerSandbox("image", 10, 5, client):
            pass
    container.remove.assert_called_once_with(force=True, v=True)


def test_multichunk_hidden_staging_protects_only_after_last_write():
    client = MagicMock()
    client.api.exec_start.return_value = [b""]
    client.api.exec_inspect.return_value = {"ExitCode": 0}
    with DockerSandbox("image", 10, 5, client) as box:
        box.upload({"hidden.py": "a" * 30000}, evaluation=True)
    calls = client.api.exec_create.call_args_list
    assert len(calls) == 2
    assert all(call.kwargs["user"] == "0:0" for call in calls)
    assert calls[0].args[1][-1] == "0"
    assert calls[1].args[1][-1] == "1"


def test_redaction_preserves_valid_json_for_escaped_secret(tmp_path, monkeypatch):
    secret = 'secret-with-"quotes"-and-\n-newline'
    monkeypatch.setenv("PRIVATE_TOKEN", secret)
    trace = Trace(tmp_path / "trace.jsonl", "id")
    trace.event("output", {"message": secret})
    assert json.loads(trace.path.read_text())["data"]["message"] == "[REDACTED]"


def test_owned_docker_client_closed_even_when_container_removal_fails(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("reflexforge.sandbox.manager.docker.from_env", lambda **kw: client)
    box = DockerSandbox("image", 10, 5)
    box.container = client.containers.create.return_value
    box.container.remove.side_effect = RuntimeError("remove failed")
    with pytest.raises(RuntimeError, match="remove failed"):
        box.close()
    client.close.assert_called_once()
