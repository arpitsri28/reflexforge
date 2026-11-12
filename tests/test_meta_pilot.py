"""All API work is mocked. Recorded real inputs are used only as fixture data."""

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from conftest import ROOT
from test_benchmark import mocked_runner
from typer.testing import CliRunner

from reflexforge.benchmark.cli import settings_for
from reflexforge.benchmark.suites import benchmark_artifacts
from reflexforge.cli import app
from reflexforge.meta.demo import SyntheticAPI, synthetic_reflection
from reflexforge.meta.pilot import plan_pilot, run_pilot
from reflexforge.meta.reuse import select_training_failures

A = "2508458d048f41489d1cc51cb6fea948"
B = "9fd09c6ad0f14d74913bca37107588dd"
R1 = "2c1b9b2afdbf4039a7342df938ce154d"
R2 = "5563b7195e674d4f976e06f82442ec42"
R3 = "627b7c1a48954a358f1ead081f7d7e5c"


@pytest.fixture
def project(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    data = tmp_path / "suites/repobench"
    (data / "benchmark").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "suites/repobench/benchmark/manifest.json", data / "benchmark/manifest.json"
    )
    for task in ("task_101", "task_102", "task_103"):
        shutil.copytree(ROOT / "suites/repobench/tasks/train" / task, data / "tasks/train" / task)
    store = benchmark_artifacts(tmp_path, "repobench") / "real"
    store.mkdir(parents=True)
    # Build real-shaped admission fixtures entirely offline. synthetic=False here tests
    # admission validation; these are not actual experiments or evidence of outcomes.
    import yaml

    from reflexforge.benchmark.manifest import load_manifest, resolve_entry
    from reflexforge.benchmark.storage import BenchmarkState
    from reflexforge.schema import Budget, RunResult
    from reflexforge.storage.database import Database
    from reflexforge.storage.traces import Trace
    from reflexforge.worker.config import AgentConfig

    config = AgentConfig.load(tmp_path / "config")
    budget = Budget(
        max_steps=20,
        max_tokens=24000,
        response_tokens=2048,
        wall_seconds=240,
        command_seconds=30,
        retry_limit=0,
    )
    expected = config.model_copy(update={"params": budget})
    manifest = load_manifest(data)
    state = BenchmarkState(store)
    for exp, specs in (
        (A, [(R1, "task_101", False)]),
        (B, [(R2, "task_102", False), (R3, "task_103", True)]),
    ):
        directory = store / "experiments" / exp
        snapshot = directory / "configs/static"
        shutil.copytree(tmp_path / "config", snapshot)
        (snapshot / "params.yaml").write_text(yaml.safe_dump(budget.model_dump()))
        entries = [e for e in manifest.entries if e.id in {t for _, t, _ in specs}]
        metadata = {
            "suite": "repobench",
            "synthetic": False,
            "bank_version": manifest.version,
            "image_id": "mock-image",
            "source_versions": {"static": config.version},
            "config_versions": {"static": expected.version},
            "entries": [e.model_dump() for e in entries],
            "settings": {
                "suite": "repobench",
                "split": "train",
                "worker_model": "gpt-5.4-mini",
                "worker_temperature": 0.0,
                "worker_reasoning_effort": "none",
                "run_budget": budget.model_dump(),
            },
        }
        with state.connect() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?,0,?,'finished')", (exp, json.dumps(metadata))
            )
        worker = Database(directory / "runs/experiments.sqlite3")
        for run, task_id, passed in specs:
            task, _, _ = resolve_entry(data, next(e for e in entries if e.id == task_id))
            result = RunResult(
                run_id=run,
                task_id=task_id,
                model="gpt-5.4-mini",
                config_version=expected.version,
                termination="completed",
                evaluation="passed" if passed else "failed",
            )
            trace = Trace(directory / "runs/traces" / (run + ".jsonl"), run)
            trace.event(
                "run_start",
                {
                    "task": task.model_dump(exclude={"hidden_test"}),
                    "config_version": expected.version,
                    "synthetic": False,
                },
            )
            trace.event(
                "worker_start",
                {
                    "model": "gpt-5.4-mini",
                    "provider": "openai",
                    "sampling": {"temperature": 0.0, "reasoning_effort": "none"},
                    "budget": budget.model_dump(),
                    "config": expected.model_dump(),
                },
            )
            trace.event("tool_call", {"name": "read_file", "arguments": '{"path":"source.py"}'})
            trace.event("evaluation", {"output": "PRIVATE_EVALUATOR_SENTINEL"})
            trace.event("patch", {"diff": "PRIVATE_PATCH_SENTINEL"})
            trace.event("run_end", result.model_dump())
            worker.start(run, task_id, "train", False)
            worker.finish(result, trace)
            payload = {
                **result.model_dump(),
                "suite": "repobench",
                "bank_version": manifest.version,
                "source_config_version": config.version,
                "execution_budget": budget.model_dump(),
                "condition": "static",
                "attempt": 0,
                "image_id": "mock-image",
            }
            with state.connect() as db:
                db.execute(
                    "INSERT INTO benchmark_cells VALUES (?,?,0,'static',?,?)",
                    (exp, task_id, "solved" if passed else "coding_failure", json.dumps(payload)),
                )
    return tmp_path


@pytest.fixture
def limits(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("OPENAI_META_MODEL", "gpt-5.4-mini")
    for prefix in ("REFLEXFORGE_", "REFLEXFORGE_META_"):
        monkeypatch.setenv(prefix + "INPUT_PRICE", "0.75")
        monkeypatch.setenv(prefix + "OUTPUT_PRICE", "4.5")
    return settings_for("dev", "static,candidate", 1, 84, 60000, 0.30, "repobench")


def select(project, limits, runs=None, experiments=None):
    return select_training_failures(
        project, limits, project / "config", run_ids=runs or [], experiment_ids=experiments or []
    )


def test_reuse_by_run_and_experiment_is_bounded_isolated_and_read_only(
    project, limits, monkeypatch
):
    store = benchmark_artifacts(project, "repobench") / "real"
    paths = [
        store / "optimization.sqlite3",
        *store.rglob("*.jsonl"),
        *store.rglob("experiments.sqlite3"),
    ]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    original = Path.read_text

    def guard(path, *args, **kwargs):
        if any(
            x in str(path)
            for x in (
                "tasks/dev/",
                "tasks/test/",
                "references/",
                "specification.json",
                "baseline-analysis",
            )
        ):
            raise AssertionError("private or human analysis material accessed")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guard)
    selected = select(project, limits, [R1, R2], [B])
    assert {f.run_id for f in selected.failures} == {R1, R2}
    assert len(selected.sources) == 3
    assert next(r for r in selected.sources if r["run_id"] == R3)["used_for_reflection"] is False
    for failure in selected.failures:
        for event in failure.events.values():
            text = event["recorded"]
            assert all(
                x not in text
                for x in (
                    '"kind": "evaluation"',
                    '"kind": "patch"',
                    '"kind": "run_end"',
                    "test_account_and_key_delimiters_do_not_alias",
                    "test_cancelled_acquisition_releases",
                    "PRIVATE_EVALUATOR_SENTINEL",
                    "PRIVATE_PATCH_SENTINEL",
                )
            )
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("synthetic", True),
        ("split", "dev"),
        ("split", "test"),
        ("worker_model", "other-model"),
        ("bank_version", "wrong"),
        ("source_config", "wrong"),
        ("worker_temperature", 1),
        ("budget", 1),
    ],
)
def test_reject_mismatched_experiment_provenance(project, limits, field, value):
    dbpath = benchmark_artifacts(project, "repobench") / "real/optimization.sqlite3"
    with sqlite3.connect(dbpath) as db:
        raw = json.loads(
            db.execute("SELECT settings FROM experiments WHERE id=?", (A,)).fetchone()[0]
        )
        if field == "synthetic":
            db.execute("UPDATE experiments SET synthetic=1 WHERE id=?", (A,))
        elif field == "bank_version":
            raw[field] = value
        elif field == "source_config":
            raw["source_versions"]["static"] = value
        elif field == "budget":
            raw["settings"]["run_budget"]["max_steps"] = value
        else:
            raw["settings"][field] = value
        db.execute("UPDATE experiments SET settings=? WHERE id=?", (json.dumps(raw), A))
    with pytest.raises(ValueError):
        select(project, limits, [R1])


@pytest.mark.parametrize("kind", ["trace", "workerdb", "cell", "symlink"])
def test_reject_corrupted_or_escaping_records(project, limits, kind, tmp_path):
    store = benchmark_artifacts(project, "repobench") / "real"
    directory = store / "experiments" / A
    trace = directory / "runs/traces" / f"{R1}.jsonl"
    if kind == "trace":
        trace.write_text(
            trace.read_text().replace('"run_id": "' + R1 + '"', '"run_id": "wrong"', 1)
        )
    elif kind == "symlink":
        outside = tmp_path / "outside.jsonl"
        trace.rename(outside)
        trace.symlink_to(outside)
    elif kind == "workerdb":
        with sqlite3.connect(directory / "runs/experiments.sqlite3") as db:
            db.execute("UPDATE runs SET synthetic=1")
    else:
        with sqlite3.connect(store / "optimization.sqlite3") as db:
            row = json.loads(
                db.execute(
                    "SELECT result FROM benchmark_cells WHERE experiment_id=?", (A,)
                ).fetchone()[0]
            )
            row["model"] = "wrong"
            db.execute(
                "UPDATE benchmark_cells SET result=? WHERE experiment_id=?", (json.dumps(row), A)
            )
    with pytest.raises(ValueError):
        select(project, limits, [R1])


def test_explicit_success_unknown_ids_and_heldout_selection_rejected(project, limits):
    for runs in ([R3], ["a" * 32], ["../escape"]):
        with pytest.raises(ValueError):
            select(project, limits, runs)
    with pytest.raises(ValueError):
        select(project, limits)
    for dev in (["task_101"], ["task_111"], []):
        with pytest.raises(ValueError):
            plan_pilot(
                project, limits, project / "config", run_ids=[R1], experiment_ids=[], dev_tasks=dev
            )


class MockMeta(SyntheticAPI):
    def __init__(self, mode="valid"):
        super().__init__()
        self.payloads = []
        self.mode = mode

    def create(self, **kwargs):
        payload = json.loads(kwargs["input"][0]["content"])
        if kwargs["instructions"].startswith("Analyze"):
            self.payloads.append(payload)
            content = synthetic_reflection(payload, empty=self.mode == "empty")
        elif kwargs["instructions"].startswith("Propose"):
            self.payloads.append(payload)
            content = {
                "target_file": "config/params.yaml"
                if self.mode == "invalid"
                else "config/system_prompt.md",
                "change_type": "modify_prompt",
                "hypothesis": "Mocked hypothesis",
                "justification": "Mocked evidence",
                "proposed_content": payload["current_config"]["system_prompt"]
                + "\nMocked general strategy.\n",
            }
        else:
            return super().create(**kwargs)
        response = super().create(
            model=kwargs["model"],
            input=[{"content": "{}"}],
            instructions="mock",
            max_output_tokens=128,
        )
        response.output_text = json.dumps(content)
        return response


def test_mocked_full_pilot_shared_budget_candidate_isolation_and_audit(project, limits):
    # Controller fixture upload only; these bytes are never sent to a meta prompt.
    source = ROOT / "suites/repobench/tasks/dev/task_107"
    shutil.copytree(source, project / "suites/repobench/tasks/dev/task_107")
    base = {
        str(p.relative_to(project / "config")): p.read_bytes()
        for p in (project / "config").rglob("*")
        if p.is_file()
    }
    api = MockMeta()
    captured = []
    result = run_pilot(
        project,
        limits,
        project / "config",
        run_ids=[R1, R2],
        experiment_ids=[],
        dev_tasks=["task_107"],
        synthetic=True,
        client=api,
        runner=mocked_runner(captured),
    )
    audit = json.loads(Path(result["audit"]).read_text())
    assert result["status"] == "finished" and result["promotion"] is False
    assert len(api.payloads) == 2 and len(captured) == 2
    assert all(task == "task_107" for task, _, _, _ in captured)
    assert audit["comparison"]["promotion"] is False
    assert audit["comparison"]["paired_attempts"] == 1
    assert (
        result["usage"]["api_calls"] == 8
    )  # Two meta generations + two worker generations + counts.
    assert audit["proposal"] and audit["candidate_version"]
    assert len(audit["evaluation_outcomes"]) == 2
    assert {
        str(p.relative_to(project / "config")): p.read_bytes()
        for p in (project / "config").rglob("*")
        if p.is_file()
    } == base
    assert not list((project / "artifacts/optimization").rglob("active.json"))
    prompt = json.dumps(api.payloads)
    assert (
        "evaluation_command" not in prompt and "test_cancelled_acquisition_releases" not in prompt
    )
    assert "baseline-analysis" not in prompt and '"kind": "evaluation"' not in prompt
    assert all(
        c.params == captured[0][2].params and c.tools == captured[0][2].tools
        for _, _, c, _ in captured
    )


@pytest.mark.parametrize(
    "mode,cap,status,calls",
    [
        ("empty", 84, "inconclusive", 2),
        ("invalid", 84, "failed", 4),
        ("valid", 1, "budget_exhausted", 1),
    ],
)
def test_pilot_no_evidence_invalid_proposal_and_global_cap(
    project, limits, mode, cap, status, calls
):
    limits.max_api_calls = cap
    result = run_pilot(
        project,
        limits,
        project / "config",
        run_ids=[R1],
        experiment_ids=[],
        dev_tasks=["task_107"],
        synthetic=True,
        client=MockMeta(mode),
        runner=mocked_runner(),
    )
    assert result["status"] == status and result["usage"]["api_calls"] == calls
    audit = json.loads(Path(result["audit"]).read_text())
    assert audit["promotion"] is False
    if mode == "invalid":
        assert audit["proposal"] and "candidate_version" not in audit


def test_cli_preflight_constructs_no_clients(project, limits, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("client constructed")

    monkeypatch.setattr("reflexforge.meta.pilot.openai.OpenAI", forbidden)
    monkeypatch.setattr("reflexforge.benchmark.runner.docker.from_env", forbidden)
    response = CliRunner().invoke(
        app, ["meta-pilot", "--root", str(project), "--experiment-ids", A + "," + B]
    )
    assert response.exit_code == 0, response.output
    data = json.loads(response.output)
    assert data["paid_requests_made"] is False and data["training_worker_reruns"] == 0
    assert len(data["source_runs"]) == 3
    assert data["settings"]["max_tokens"] == 200000
    assert data["settings"]["max_api_calls"] == 200
    assert data["hard_usd_cap"] == 0.50
    assert data["settings"]["run_budget"] == limits.run_budget.model_dump()
    assert data["tokens_available_for_meta_after_full_worker_allocations"] == 152000
    assert data["uncapped_http_calls_including_meta_and_counting"] == 84
    assert not (project / "artifacts/optimization").exists()


@pytest.mark.parametrize("cap", ["calls", "tokens", "usd"])
def test_shared_caps_include_meta_and_stop_partial_worker_execution(project, limits, cap):
    shutil.copytree(
        ROOT / "suites/repobench/tasks/dev/task_107",
        project / "suites/repobench/tasks/dev/task_107",
    )
    if cap == "calls":
        limits.max_api_calls = 5
    elif cap == "tokens":
        limits.max_tokens = 200
    else:
        limits.max_usd = 0.0001
    result = run_pilot(
        project,
        limits,
        project / "config",
        run_ids=[R1],
        experiment_ids=[],
        dev_tasks=["task_107"],
        synthetic=True,
        client=MockMeta(),
        runner=mocked_runner(),
    )
    assert result["status"] == "budget_exhausted"
    assert result["usage"]["api_calls"] == (5 if cap == "calls" else 1)
    assert result["usage"]["tokens"] <= limits.max_tokens
    assert result["usage"]["usd_upper_bound"] <= limits.max_usd
    audit = json.loads(Path(result["audit"]).read_text())
    if cap == "calls":
        assert audit["proposal"] and audit["candidate_version"]
        assert {c["status"] for c in audit["evaluation_outcomes"]} == {
            "pending",
            "budget_exhausted",
        }
        assert audit["comparison"]["promotion"] is False


def test_interrupted_candidate_run_keeps_partial_audit_without_promotion(project, limits):
    shutil.copytree(
        ROOT / "suites/repobench/tasks/dev/task_107",
        project / "suites/repobench/tasks/dev/task_107",
    )

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_pilot(
            project,
            limits,
            project / "config",
            run_ids=[R1],
            experiment_ids=[],
            dev_tasks=["task_107"],
            synthetic=True,
            client=MockMeta(),
            runner=interrupted,
        )
    audit_path = next(
        (project / "artifacts/optimization/repobench/pilots/synthetic").glob("*/audit.json")
    )
    audit = json.loads(audit_path.read_text())
    assert audit["status"] == "interrupted" and audit["promotion"] is False
    assert audit["proposal"] and audit["candidate_version"]
    assert {c["status"] for c in audit["evaluation_outcomes"]} == {"pending", "interrupted"}
    assert audit["usage"]["api_calls"] == 4


def test_source_task_identity_rejects_dev_before_reading_dev_material(project, limits, monkeypatch):
    store = benchmark_artifacts(project, "repobench") / "real"
    with sqlite3.connect(store / "optimization.sqlite3") as db:
        db.execute("UPDATE benchmark_cells SET task_id='task_107' WHERE experiment_id=?", (A,))
    original = Path.read_text

    def guard(path, *args, **kwargs):
        assert "/tasks/dev/" not in str(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guard)
    with pytest.raises(ValueError, match="only training"):
        select(project, limits, [R1])
