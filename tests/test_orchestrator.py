import json
import time
from unittest.mock import MagicMock

from conftest import ROOT
from test_worker import response
from typer.testing import CliRunner

from reflexforge.cli import app
from reflexforge.orchestrator import run_worker
from reflexforge.schema import CommandResult
from reflexforge.storage.database import Database
from reflexforge.tasks import load_tasks


def test_dry_run_is_explicit_and_never_runs_code(tmp_path, config):
    task, directory = load_tasks(ROOT / "tasks")[0]
    factory = MagicMock()
    result = run_worker(task, directory, config, tmp_path, dry_run=True, factory=factory)
    factory.assert_not_called()
    assert result.synthetic
    assert result.evaluation == "not_run"
    assert result.termination == "synthetic_plan_only"
    assert Database(tmp_path / "experiments.sqlite3").results() == []
    events = [
        json.loads(line) for line in next((tmp_path / "traces").glob("*")).read_text().splitlines()
    ]
    assert events[-1]["kind"] == "run_end"


def test_independent_evaluator_and_patch_flow(tmp_path, config, monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "unit-test-model")
    task, directory = load_tasks(ROOT / "tasks")[0]
    worker, evaluator = MagicMock(), MagicMock()
    worker.deadline = time.monotonic() + 100
    worker.read.return_value = "def first(items, n):\n    return items[:n]\n"
    evaluator.execute.return_value = CommandResult(exit_code=0, output="")
    first, second = MagicMock(), MagicMock()
    first.__enter__.return_value = worker
    second.__enter__.return_value = evaluator
    factory = MagicMock(side_effect=[first, second])
    api = MagicMock()
    api.responses.input_tokens.count.return_value.input_tokens = 20
    api.responses.create.return_value = response([])
    result = run_worker(task, directory, config, tmp_path, client=api, factory=factory)
    assert result.evaluation == "passed"
    assert "items[:n]" in result.patch
    assert factory.call_count == 2
    assert all(not c.kwargs.get("evaluation") for c in worker.upload.call_args_list)
    assert evaluator.upload.call_args_list[-1].kwargs == {"evaluation": True}
    assert first.__exit__.called and second.__exit__.called
    assert Database(tmp_path / "experiments.sqlite3").results()[0]["evaluation"] == "passed"


def test_cli_lists_and_rejects_unknown_task():
    runner = CliRunner()
    result = runner.invoke(app, ["list-tasks", "--root", str(ROOT)])
    assert result.exit_code == 0 and "task_001" in result.output
    result = runner.invoke(app, ["run-worker", "--task", "nope", "--root", str(ROOT)])
    assert result.exit_code != 0 and "unknown task" in result.output


def test_visible_completion_does_not_override_hidden_failure(tmp_path, config, monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "unit-model")
    task, directory = load_tasks(ROOT / "tasks")[0]
    worker, evaluator = MagicMock(), MagicMock()
    worker.deadline = time.monotonic() + 100
    worker.read.return_value = (directory / "repo" / "solution.py").read_text()
    evaluator.execute.return_value = CommandResult(exit_code=1, output="AssertionError")
    contexts = [MagicMock(), MagicMock()]
    contexts[0].__enter__.return_value = worker
    contexts[1].__enter__.return_value = evaluator
    api = MagicMock()
    api.responses.input_tokens.count.return_value.input_tokens = 20
    api.responses.create.return_value = response([])
    result = run_worker(
        task, directory, config, tmp_path, client=api, factory=MagicMock(side_effect=contexts)
    )
    assert result.termination == "completed"
    assert result.evaluation == "failed"
    assert result.failure_category == "incorrect_patch"


def test_missing_key_fails_before_starting_sandbox(tmp_path, config, monkeypatch):
    import pytest

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    task, directory = load_tasks(ROOT / "tasks")[0]
    factory = MagicMock()
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        run_worker(task, directory, config, tmp_path, factory=factory)
    factory.assert_not_called()


def test_doctor_checks_default_model_without_generation(monkeypatch):
    from reflexforge.worker.agent import DEFAULT_MODEL

    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-secret-key")
    api_constructor = MagicMock()
    docker_constructor = MagicMock()
    monkeypatch.setattr("reflexforge.cli.openai.OpenAI", api_constructor)
    monkeypatch.setattr("reflexforge.cli.docker.from_env", docker_constructor)
    result = CliRunner().invoke(app, ["doctor", "--root", str(ROOT), "--api"])
    assert result.exit_code == 0
    client = api_constructor.return_value.__enter__.return_value
    client.models.retrieve.assert_called_once_with(DEFAULT_MODEL)
    client.responses.create.assert_not_called()
    assert api_constructor.call_args.kwargs["max_retries"] == 0
    assert "unit-test-secret-key" not in result.output


def test_doctor_never_prints_api_error_body(monkeypatch):
    import httpx
    import openai

    api_constructor = MagicMock()
    client = api_constructor.return_value.__enter__.return_value
    client.models.retrieve.side_effect = openai.AuthenticationError(
        "Incorrect API key sk-proj-never-print-this",
        body=None,
        response=httpx.Response(401, request=httpx.Request("GET", "https://example.invalid")),
    )
    monkeypatch.setattr("reflexforge.cli.openai.OpenAI", api_constructor)
    monkeypatch.setattr("reflexforge.cli.docker.from_env", MagicMock())
    result = CliRunner().invoke(app, ["doctor", "--root", str(ROOT), "--api"])
    assert result.exit_code == 1
    assert "sk-proj-" not in result.output
    assert "AuthenticationError" in result.output


def test_doctor_closes_plain_docker_client(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    # A plain object deliberately provides no context-manager protocol.
    client = SimpleNamespace(ping=Mock(), images=SimpleNamespace(get=Mock()), close=Mock())
    monkeypatch.setattr("reflexforge.cli.docker.from_env", Mock(return_value=client))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    checks = json.loads(result.output)
    assert checks["docker"] == "ready" and checks["image"] == "ready"
    client.ping.assert_called_once()
    client.close.assert_called_once()


def test_doctor_closes_docker_client_on_failure(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    for stage in ("ping", "image"):
        client = SimpleNamespace(ping=Mock(), images=SimpleNamespace(get=Mock()), close=Mock())
        operation = client.ping if stage == "ping" else client.images.get
        operation.side_effect = RuntimeError("Docker check failed")
        monkeypatch.setattr("reflexforge.cli.docker.from_env", Mock(return_value=client))
        result = CliRunner().invoke(app, ["doctor", "--root", str(ROOT)])
        assert result.exit_code == 1
        assert "Docker check failed" in result.output
        client.close.assert_called_once()


def test_global_budget_exhaustion_is_not_a_controller_or_coding_failure(tmp_path, config):
    import pytest

    from reflexforge.benchmark.runner import classify
    from reflexforge.meta.budget import BudgetExceeded

    task, directory = load_tasks(ROOT / "tasks")[0]
    box = MagicMock()
    box.deadline = time.monotonic() + 100
    context = MagicMock()
    context.__enter__.return_value = box
    factory = MagicMock(return_value=context)
    api = MagicMock()
    api.responses.input_tokens.count.side_effect = BudgetExceeded("overall token limit reached")
    with pytest.raises(BudgetExceeded):
        run_worker(task, directory, config, tmp_path, client=api, factory=factory)
    row = Database(tmp_path / "experiments.sqlite3").results()[0]
    assert row["termination"] == "budget_exhausted"
    assert row["evaluation"] == "not_run"
    assert row["failure_category"] == "execution_budget_exhausted"
    assert classify(row) == "unevaluated"
    assert factory.call_count == 1  # No evaluator or automatic retry.
    assert context.__exit__.called
