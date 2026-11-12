import json
import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from conftest import ROOT
from pydantic import ValidationError

from reflexforge.evaluation.gatekeeper import PairedRun, compare
from reflexforge.meta.budget import BudgetedClient, BudgetExceeded, UsageLedger
from reflexforge.meta.demo import SyntheticAPI, run_demo
from reflexforge.meta.optimizer import Optimizer, optimization_directory
from reflexforge.meta.reflector import Reflector, collect_failure
from reflexforge.meta.schemas import OptimizationSettings, Proposal, Reflection
from reflexforge.meta.state import OptimizationState, exclusive_lock
from reflexforge.meta.versioning import VersionStore, active_config_path, candidate_snapshot
from reflexforge.schema import RunResult
from reflexforge.tasks import load_tasks
from reflexforge.worker.config import AgentConfig


@pytest.fixture
def project(tmp_path):
    for name in ("config", "tasks"):
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path


def settings(**updates):
    return OptimizationSettings(worker_model="worker-test", meta_model="meta-test", **updates)


def proposal(config, **updates):
    return Proposal.model_validate(
        {
            "target_file": "config/system_prompt.md",
            "change_type": "modify_prompt",
            "hypothesis": "Reproduce before editing",
            "justification": "Observed training evidence",
            "proposed_content": config.system_prompt + "\nReproduce before editing.\n",
            **updates,
        }
    )


def result(task_id="task_001", version="base", passed=False, synthetic=True, **updates):
    return RunResult.model_validate(
        {
            "run_id": "run_" + task_id,
            "task_id": task_id,
            "config_version": version,
            "model": "worker-test",
            "synthetic": synthetic,
            "termination": "completed",
            "evaluation": "passed" if passed else "failed",
            "input_tokens": 100,
            "output_tokens": 20,
            "tool_calls": 1,
            "wall_seconds": 1.0,
            **updates,
        }
    )


def make_pairs(count=5, after=True):
    return [
        PairedRun(
            f"task_{i:03}",
            0,
            result(f"task_{i:03}"),
            result(f"task_{i:03}", version="candidate", passed=after),
        )
        for i in range(count)
    ]


def gate(pairs, repetitions=1, count=None):
    return compare(
        pairs,
        sorted({p.task_id for p in pairs}) if count is None else count,
        repetitions,
        "base",
        "candidate",
        "worker-test",
        True,
    )


def test_candidate_isolation_and_complete_snapshot(project):
    base = AgentConfig.load(project / "config")
    candidate = candidate_snapshot(project / "config", project / "candidate", proposal(base))
    assert candidate.version != base.version
    assert AgentConfig.load(project / "config").version == base.version
    assert candidate.params == base.params and candidate.tools == base.tools
    assert candidate.skills == base.skills


@pytest.mark.parametrize(
    "target",
    [
        "../config/system_prompt.md",
        "/config/system_prompt.md",
        "config/../params.yaml",
        "config/params.yaml",
        "config/tools.yaml",
        "src/reflexforge/evaluation/evaluator.py",
        "config/skills/../../escape.md",
        "config/skills/nested/name.md",
        "config/.env",
    ],
)
def test_unauthorized_proposal_targets_rejected(project, target):
    config = AgentConfig.load(project / "config")
    with pytest.raises(ValueError, match="unauthorized"):
        candidate_snapshot(
            project / "config", project / "candidate", proposal(config, target_file=target)
        )
    assert AgentConfig.load(project / "config").version == config.version


def test_strict_proposal_schema_and_workflow(project):
    config = AgentConfig.load(project / "config")
    with pytest.raises(ValidationError):
        Proposal.model_validate({**proposal(config).model_dump(), "tools": ["new-tool"]})
    with pytest.raises(ValueError):
        candidate_snapshot(
            project / "config",
            project / "candidate",
            proposal(
                config,
                target_file="config/workflow.yaml",
                change_type="modify_workflow",
                proposed_content="steps: [test]\nunauthorized: true\n",
            ),
        )


def test_skill_addition_and_symlink_rejection(project):
    config = AgentConfig.load(project / "config")
    new = proposal(
        config,
        target_file="config/skills/imports.md",
        change_type="upsert_skill",
        proposed_content="Check module search paths and package imports.",
    )
    candidate = candidate_snapshot(project / "config", project / "candidate", new)
    assert "imports" in candidate.skills and "imports" not in config.skills
    (project / "config" / "skills" / "escape.md").symlink_to(project / "config" / "params.yaml")
    with pytest.raises(ValueError, match="symlink"):
        candidate_snapshot(project / "config", project / "second", new)


def test_versioning_accept_reject_and_rollback(project):
    directory = project / "store"
    with exclusive_lock(directory):
        store = VersionStore(directory)
        base = store.commit(project / "config", {"kind": "baseline"}, None)
        config = AgentConfig.load(project / "config")
        candidate_snapshot(project / "config", project / "candidate", proposal(config))
        # A rejected snapshot never touches the active pointer.
        assert store.active()[0] == base
        accepted = store.commit(project / "candidate", {"decision": {"accepted": True}}, base)
        assert store.active()[0] == accepted
        assert len(store.history()) == 2
        assert store.git("rev-list", "--count", "HEAD") == "2"
        store.rollback(base)
        assert store.active()[0] == base
        assert AgentConfig.load(project / "config").version == base
        with pytest.raises(RuntimeError):
            store.commit(project / "candidate", {}, accepted)
        with pytest.raises(ValueError):
            store.rollback("../escape")


def test_concurrent_state_mutations_are_locked(tmp_path):
    with exclusive_lock(tmp_path), pytest.raises(RuntimeError, match="another optimization"):
        with exclusive_lock(tmp_path):
            pass


def test_gatekeeper_accepts_strong_paired_evidence():
    decision = gate(make_pairs())
    assert decision["accepted"] and decision["task_sign_p"] == pytest.approx(1 / 32)
    assert decision["candidate"]["solved"] == 5


def test_gatekeeper_rejects_regression_and_resource_excess():
    pairs = make_pairs()
    pairs[0].incumbent.evaluation = "passed"
    pairs[0].candidate.evaluation = "failed"
    assert gate(pairs)["reason"] == "success_regression"
    pairs = make_pairs()
    pairs[0].candidate.input_tokens = 10000
    assert gate(pairs)["reason"] == "tokens_regression"


def test_one_task_repeated_many_times_is_inconclusive():
    pairs = [
        PairedRun("task_001", i, result(), result(version="candidate", passed=True))
        for i in range(10)
    ]
    decision = gate(pairs, repetitions=10)
    assert decision["outcome"] == "inconclusive"
    assert decision["task_wins"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("synthetic", False),
        ("usage_incomplete", True),
        ("model", "other-model"),
        ("config_version", "wrong"),
        ("termination", "api_error"),
        ("evaluation", "sandbox_error"),
    ],
)
def test_unreliable_or_inequivalent_evaluation_rejected(field, value):
    pairs = make_pairs()
    setattr(pairs[0].candidate, field, value)
    assert gate(pairs)["reason"] == "unreliable_evaluation"


def test_missing_or_duplicate_comparisons_rejected():
    pairs = make_pairs()
    assert gate(pairs + [pairs[0]])["reason"] == "unreliable_evaluation"
    assert gate(pairs, count=["task_999"])["reason"] == "unreliable_evaluation"


def failed_trace(project, tmp_path):
    task, _ = load_tasks(project / "tasks", "train")[0]
    run = result(task_id=task.id)
    path = tmp_path / "trace.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {"run_id": run.run_id, "kind": "tool_call", "data": {"name": "edit_file"}}
                ),
                "{bad json",
                json.dumps(
                    {"run_id": run.run_id, "kind": "evaluation", "data": "HIDDEN-EVALUATOR-MARKER"}
                ),
                json.dumps({"run_id": "wrong", "kind": "tool_result", "data": "WRONG-RUN-MARKER"}),
            ]
        )
    )
    return task, run, path


def test_reflection_uses_only_recorded_worker_evidence(project, tmp_path):
    task, run, path = failed_trace(project, tmp_path)
    failure = collect_failure(task, run, path, synthetic=True)
    assert list(failure.events) == [0]
    assert failure.warnings
    reflection = Reflector(SyntheticAPI(), "meta-test").analyze([failure])
    assert reflection.diagnoses[0].evidence[0].quote == "edit_file"
    assert "HIDDEN-EVALUATOR-MARKER" not in str(failure)
    assert "WRONG-RUN-MARKER" not in str(failure)
    with pytest.raises(ValidationError):
        Reflection.model_validate({"diagnoses": [{"root_cause": "unsupported"}]})


def test_reflector_rejects_invented_evidence(project, tmp_path):
    task, run, path = failed_trace(project, tmp_path)
    failure = collect_failure(task, run, path, synthetic=True)
    api = SyntheticAPI()
    output = api.create(
        instructions="Analyze",
        input=[
            {
                "content": json.dumps(
                    {
                        "failures": [
                            {
                                "run_id": run.run_id,
                                "events": failure.events,
                                "execution": failure.execution,
                            }
                        ]
                    }
                )
            }
        ],
    )
    data = json.loads(output.output_text)
    data["diagnoses"][0]["evidence"][0]["event_index"] = 999
    api.responses.create = lambda **kw: SimpleNamespace(
        status="completed", output_text=json.dumps(data)
    )
    with pytest.raises(ValueError, match="unrecorded"):
        Reflector(api, "meta-test").analyze([failure])


@pytest.mark.parametrize("split", ["dev", "test"])
def test_dev_and_test_never_enter_reflection(project, tmp_path, split):
    task, run, path = failed_trace(project, tmp_path)
    with pytest.raises(ValueError, match="training"):
        collect_failure(task.model_copy(update={"split": split}), run, path, synthetic=True)
    run.evaluation = "passed"
    with pytest.raises(ValueError, match="failures"):
        collect_failure(task, run, path, synthetic=True)


def test_budget_validation_fails_closed_without_pricing():
    with pytest.raises(ValueError, match="USD cap"):
        settings(max_usd=0.1)


def ledger_client(tmp_path, limits, api=None):
    state = OptimizationState(tmp_path)
    ledger = UsageLedger(state, "experiment", limits)
    return BudgetedClient(
        api or SyntheticAPI(), ledger, "worker", limits.worker_model, limits.worker_prices
    ), ledger


@pytest.mark.parametrize(
    "limits",
    [
        settings(max_api_calls=1),
        settings(max_tokens=100),
        settings(max_usd=0.00001, worker_prices=(1.0, 2.0), meta_prices=(1.0, 2.0)),
    ],
)
def test_api_budget_reserves_before_generation(tmp_path, limits):
    api = MagicMock()
    api.responses.input_tokens.count.return_value.input_tokens = 100
    client, ledger = ledger_client(tmp_path, limits, api)
    common = dict(
        model=limits.worker_model,
        instructions="Synthetic worker",
        input=[{"role": "user", "content": "{}"}],
    )
    client.responses.input_tokens.count(**common)
    with pytest.raises(BudgetExceeded):
        client.responses.create(**common, max_output_tokens=128)
    api.responses.create.assert_not_called()
    assert ledger.summary()["api_calls"] == 1


def test_actual_usage_is_recorded_and_missing_price_is_not_zero(tmp_path):
    client, ledger = ledger_client(tmp_path, settings())
    common = dict(model="worker-test", instructions="Synthetic worker", input=[{"content": "{}"}])
    client.responses.input_tokens.count(**common)
    client.responses.create(**common, max_output_tokens=128)
    summary = ledger.summary()
    assert summary["tokens"] == 120 and summary["api_calls"] == 2
    assert summary["usd_upper_bound"] is None


def test_unknown_usage_blocks_further_calls_and_survives_recovery(tmp_path):
    api = MagicMock()
    api.responses.input_tokens.count.return_value.input_tokens = 100
    api.responses.create.side_effect = KeyboardInterrupt
    client, ledger = ledger_client(tmp_path, settings(), api)
    common = dict(model="worker-test", input=[])
    client.responses.input_tokens.count(**common)
    with pytest.raises(KeyboardInterrupt):
        client.responses.create(**common, max_output_tokens=128)
    assert ledger.summary()["tokens"] == 228 and ledger.summary()["uncertain"]
    ledger.state.recover()
    with pytest.raises(BudgetExceeded):
        client.responses.input_tokens.count(**common)


@pytest.mark.parametrize(
    "scenario,outcome",
    [("accept", "accepted"), ("reject", "rejected"), ("no-failures", "no_failures")],
)
def test_complete_mock_optimization(project, scenario, outcome):
    before = AgentConfig.load(project / "config").version
    summary = run_demo(project, settings(), scenario)
    assert summary["synthetic"] and summary["status"] == "finished"
    directory = optimization_directory(project, True)
    state = OptimizationState(directory)
    row = state.iterations()[0]
    assert row["status"] == outcome and row["synthetic"] == 1
    assert (summary["active_version"] != before) == (outcome == "accepted")
    assert AgentConfig.load(project / "config").version == before
    assert active_config_path(project) == project / "config"  # Synthetic activation stays isolated.
    if outcome != "no_failures":
        assert len(row["data"]["dev_runs"]) == 10
        assert len({r["run_id"] for r in row["data"]["dev_runs"]}) == 10
    from reflexforge.storage.database import Database

    runs_db = next((directory / "experiments").glob("*/runs/experiments.sqlite3"))
    assert Database(runs_db).results() == []


def test_budget_exhaustion_is_audited(project):
    summary = run_demo(project, settings(max_api_calls=1), "accept")
    assert summary["status"] == "budget_exhausted"
    assert (
        OptimizationState(optimization_directory(project, True)).iterations()[0]["status"]
        == "budget_exhausted"
    )


def test_interrupted_iteration_recovered_without_paid_replay(tmp_path):
    state = OptimizationState(tmp_path)
    with state.connect() as db:
        db.execute("INSERT INTO experiments VALUES (?, 1, ?, ?)", ("exp", "{}", "running"))
    state.record("iter", "exp", 1, "running", {"candidate": "not-active"})
    state.recover()
    assert state.iterations()[0]["status"] == "interrupted"


def test_test_split_manifest_is_never_read(project):
    (project / "tasks" / "test" / "task_003" / "task.json").write_text("THIS MUST NOT BE PARSED")
    assert len(load_tasks(project / "tasks", "train")) == 18
    assert len(load_tasks(project / "tasks", "dev")) == 12
    summary = run_demo(project, settings(), "accept")
    assert summary["status"] == "finished"


def test_live_optimizer_rejects_mock_runners(project):
    with pytest.raises(ValueError, match="synthetic"):
        Optimizer(project, settings(), runner=MagicMock())


def test_reflector_structured_output_through_real_sdk_http_mock(project, tmp_path):
    import httpx
    import openai
    from test_worker import response

    from reflexforge.meta.diagnostics import GenerationDiagnostics

    task, run, path = failed_trace(project, tmp_path)
    failure = collect_failure(task, run, path, synthetic=True)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith("/input_tokens"):
            assert body["text"]["format"]["type"] == "json_schema"
            return httpx.Response(
                200, json={"object": "response.input_tokens", "input_tokens": 100}
            )
        content = SyntheticAPI().create(**body).output_text
        reply = response(
            [
                {
                    "id": "msg_meta",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": content, "annotations": []}],
                }
            ],
            input_tokens=100,
            output_tokens=20,
        )
        return httpx.Response(200, json=reply.model_dump(mode="json"))

    with openai.OpenAI(
        api_key="unit-test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as api:
        client, ledger = ledger_client(tmp_path / "ledger", settings(), api)
        diagnostics = GenerationDiagnostics(
            tmp_path / "diagnostics" / "attempt-001",
            pilot_id="mock-sdk",
            generation_attempt=1,
            accounting=ledger.summary,
        )
        reflection = Reflector(client, "worker-test").analyze([failure], diagnostics=diagnostics)
    assert reflection.diagnoses[0].evidence[0].run_id == run.run_id
    assert ledger.summary()["tokens"] == 120
    assert requests[-1][1]["text"]["format"]["strict"] is True
    assert "HIDDEN-EVALUATOR-MARKER" not in json.dumps(requests)
    captured = json.loads((diagnostics.directory / "response.json").read_text())
    assert captured["raw_response"]["status"] == "completed"
    assert json.loads(captured["output_text"])["attributions"]
    assert (
        json.loads((diagnostics.directory / "accounting.json").read_text())["generation_delta"][
            "tokens"
        ]
        == 120
    )


def test_rejection_feedback_does_not_expose_dev_information(tmp_path):
    state = OptimizationState(tmp_path)
    with state.connect() as db:
        db.execute("INSERT INTO experiments VALUES (?, 0, ?, ?)", ("exp", "{}", "finished"))
    state.record(
        "iteration",
        "exp",
        1,
        "rejected",
        {
            "proposal": {"hypothesis": "Train-derived hypothesis"},
            "dev_runs": [{"patch": "SECRET-DEV-INFO", "task_id": "task_dev"}],
            "decision": {"reason": "SECRET-DEV-INFO"},
        },
    )
    assert state.rejected_feedback() == [
        {"hypothesis": "Train-derived hypothesis", "outcome": "rejected"}
    ]


def test_recover_pointer_published_before_iteration_finalize(tmp_path):
    state = OptimizationState(tmp_path)
    with state.connect() as db:
        db.execute("INSERT INTO experiments VALUES (?, 1, ?, ?)", ("exp", "{}", "running"))
    state.record(
        "iter",
        "exp",
        1,
        "running",
        {"candidate": "published-version", "decision": {"accepted": True}},
    )
    state.recover("published-version")
    row = state.iterations()[0]
    assert row["status"] == "accepted" and row["data"]["recovered"]


def test_git_commit_recovery_before_pointer_publication(project, monkeypatch):
    import subprocess

    store = VersionStore(project / "store")
    original_git = store.git

    def interrupted_git(*args):
        if "commit" in args:
            raise subprocess.CalledProcessError(1, "git commit")
        return original_git(*args)

    monkeypatch.setattr(store, "git", interrupted_git)
    with pytest.raises(subprocess.CalledProcessError):
        store.commit(project / "config", {"kind": "baseline"}, None)
    assert store.active() is None
    monkeypatch.setattr(store, "git", original_git)
    version = store.commit(project / "config", {"kind": "baseline"}, None)
    assert store.active()[0] == version
    assert store.history()[0]["git_commit"]


def test_multiple_rejected_iterations_are_independent_and_bounded(project):
    summary = run_demo(project, settings(max_iterations=2, max_api_calls=60), "reject")
    assert summary["status"] == "finished" and len(summary["iterations"]) == 2
    rows = OptimizationState(optimization_directory(project, True)).iterations()
    assert [row["status"] for row in rows] == ["rejected", "rejected"]
    assert rows[0]["data"]["incumbent"] == rows[1]["data"]["incumbent"]


def test_synthetic_mode_cannot_accidentally_create_real_api_client(project):
    with pytest.raises(ValueError, match="mocked"):
        Optimizer(project, settings(), synthetic=True)


def test_reservation_requires_matching_input_and_pinned_model(tmp_path):
    api = MagicMock()
    api.responses.input_tokens.count.return_value.input_tokens = 100
    client, _ = ledger_client(tmp_path, settings(), api)
    with pytest.raises(ValueError, match="model"):
        client.responses.input_tokens.count(model="other")
    client.responses.input_tokens.count(model="worker-test", input=[])
    with pytest.raises(BudgetExceeded, match="matching"):
        client.responses.create(
            model="worker-test", input=[{"role": "user", "content": "new"}], max_output_tokens=128
        )
    api.responses.create.assert_not_called()


def test_api_overrun_is_recorded_and_halts_experiment(tmp_path):
    api = SyntheticAPI()
    old_create = api.responses.create

    def too_many_tokens(**kwargs):
        reply = old_create(**kwargs)
        reply.usage.output_tokens = 10000
        return reply

    api.responses.create = too_many_tokens
    client, ledger = ledger_client(tmp_path, settings(), api)
    common = dict(model="worker-test", instructions="Synthetic worker", input=[{"content": "{}"}])
    client.responses.input_tokens.count(**common)
    with pytest.raises(BudgetExceeded, match="reservation"):
        client.responses.create(**common, max_output_tokens=128)
    assert ledger.summary()["uncertain"]
    assert ledger.summary()["tokens"] == 10100


def test_cli_full_synthetic_cycle_without_api_or_docker(project, monkeypatch):
    from typer.testing import CliRunner

    from reflexforge.cli import app

    def forbidden(*args, **kwargs):
        raise AssertionError("synthetic CLI must never create a live API or Docker client")

    monkeypatch.setattr("reflexforge.meta.optimizer.openai.OpenAI", forbidden)
    monkeypatch.setattr("reflexforge.meta.optimizer.docker.from_env", forbidden)
    runner = CliRunner()
    outcome = runner.invoke(
        app, ["optimize", "--root", str(project), "--dry-run", "--scenario", "accept"]
    )
    assert outcome.exit_code == 0
    summary = json.loads(outcome.output)
    assert summary["synthetic"] is True
    selected = runner.invoke(
        app, ["show-iteration", summary["iterations"][0], "--root", str(project), "--synthetic"]
    )
    assert json.loads(selected.output)["status"] == "accepted"
    history = runner.invoke(app, ["config-history", "--root", str(project), "--synthetic"])
    versions = json.loads(history.output)["versions"]
    assert len(versions) == 2 and all(row["git_commit"] for row in versions)
    proposals_result = runner.invoke(app, ["proposals", "--root", str(project), "--synthetic"])
    assert len(json.loads(proposals_result.output)) == 1
    baseline = next(row["version"] for row in versions if row["kind"] == "baseline")
    rollback = runner.invoke(
        app, ["rollback-config", baseline, "--root", str(project), "--synthetic"]
    )
    assert rollback.exit_code == 0 and json.loads(rollback.output)["active_version"] == baseline
    assert not optimization_directory(project, False).exists()


def test_worker_cli_uses_active_snapshot_and_explicit_config_override(project):
    from typer.testing import CliRunner

    from reflexforge.cli import app

    store = VersionStore(optimization_directory(project))
    config = AgentConfig.load(project / "config")
    base = store.commit(project / "config", {"kind": "baseline"}, None)
    candidate_snapshot(project / "config", project / "candidate", proposal(config))
    accepted = store.commit(project / "candidate", {"kind": "accepted"}, base)
    runner = CliRunner()
    active = runner.invoke(
        app, ["run-worker", "--root", str(project), "--task", "task_001", "--dry-run"]
    )
    explicit = runner.invoke(
        app,
        [
            "run-worker",
            "--root",
            str(project),
            "--task",
            "task_001",
            "--config",
            "config",
            "--dry-run",
        ],
    )
    assert active.exit_code == 0 and json.loads(active.output)["config_version"] == accepted
    assert explicit.exit_code == 0 and json.loads(explicit.output)["config_version"] == base


def test_task_snapshots_freeze_evaluation_conditions(project):
    from reflexforge.meta.optimizer import freeze_tasks

    original = project / "tasks" / "dev" / "task_002" / "repo" / "solution.py"
    content = original.read_text()
    bank = freeze_tasks(project, project / "frozen")
    original.write_text("Developer changed the fixture after experiment startup")
    task, directory = bank["dev"][0]
    assert (directory / task.repository / "solution.py").read_text() == content
    assert not (project / "frozen" / "test").exists()
