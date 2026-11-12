import json
import shutil
import uuid
from pathlib import Path

import pytest
from conftest import ROOT
from typer.testing import CliRunner

from reflexforge.benchmark.manifest import (
    digest,
    inspect_bank,
    load_manifest,
    normalized_source,
    resolve_entry,
)
from reflexforge.benchmark.runner import BenchmarkRunner, classify
from reflexforge.benchmark.settings import BenchmarkSettings, preflight
from reflexforge.benchmark.statistics import aggregate, exploratory
from reflexforge.benchmark.storage import BenchmarkState
from reflexforge.cli import app
from reflexforge.meta.demo import SyntheticAPI
from reflexforge.schema import RunResult


@pytest.fixture
def project(tmp_path):
    for name in ("tasks", "config", "benchmark"):
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path


def settings(**updates):
    return BenchmarkSettings(worker_model="worker-test", meta_model="unused-meta", **updates)


def mocked_runner(captured=None):
    def worker(
        task,
        directory,
        config,
        artifacts,
        *,
        client,
        model,
        reflection_only,
        factory,
        temperature=None,
        reasoning_effort=None,
    ):
        if captured is not None:
            captured.append((task.id, directory, config, reflection_only))
        request = dict(model=model, instructions="Synthetic worker", input=[{"content": "{}"}])
        client.responses.input_tokens.count(**request)
        client.responses.create(**request, max_output_tokens=128)
        return RunResult(
            run_id=uuid.uuid4().hex,
            task_id=task.id,
            config_version=config.version,
            model=model,
            synthetic=True,
            termination="completed",
            evaluation="passed" if reflection_only else "failed",
            input_tokens=100,
            output_tokens=20,
            wall_seconds=1.0,
            tool_calls=2,
            reflection_retries=int(reflection_only),
        )

    return worker


ENTRIES = load_manifest(ROOT).entries


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_every_fixture_has_verified_bug_and_reference(entry):
    qa = json.loads((ROOT / "benchmark" / "validation.json").read_text())
    assert qa["version"] == load_manifest(ROOT).version
    row = next(r for r in qa["results"] if r["task_id"] == entry.id)
    task, directory, overlay = resolve_entry(ROOT, entry, references=True)
    assert row["source_hash"] == entry.source_hash and row["reference_hash"] == entry.reference_hash
    assert row["valid"]
    assert row["buggy"]["visible_exit"] != 0
    assert all(code != 0 for code in row["buggy"]["regression_exits"])
    assert row["reference"]["visible_exit"] == 0
    assert row["reference"]["regression_exits"] == [0, 0]
    assert row["reference"]["deterministic_output"] and row["buggy"]["deterministic_output"]
    assert overlay and set(overlay) <= set(task.editable)
    assert not any(
        "reference" in p.name or "hidden" in p.name for p in (directory / "repo").rglob("*")
    )
    assert len(entry.coverage) >= 3


def test_manifest_distribution_families_and_near_duplicates():
    report = inspect_bank(ROOT, load_manifest(ROOT))
    assert report["split_counts"] == {"train": 18, "dev": 12, "test": 8}
    assert report["difficulty_counts"] == {"easy": 3, "medium": 20, "hard": 15}
    assert not report["near_duplicates"]
    assert len(report["category_counts"]) >= 12


def test_version_and_source_mismatch_rejected(project):
    with pytest.raises(ValueError, match="version"):
        load_manifest(project, "wrong-version")
    entry = load_manifest(project).entries[0]
    task, directory, _ = resolve_entry(project, entry)
    (directory / task.repository / task.editable[0]).write_text("developer changed fixture")
    with pytest.raises(ValueError, match="hash"):
        resolve_entry(project, entry)


def test_renamed_duplicate_detection():
    assert normalized_source({"a.py": "def compute(x): return x + 1"}) == normalized_source(
        {"b.py": "def renamed(y): return y + 9"}
    )


def test_family_isolation_and_manifest_tampering(project):
    path = project / "benchmark/manifest.json"
    raw = json.loads(path.read_text())
    raw["entries"][1]["family"] = raw["entries"][0]["family"]
    raw["version"] = digest({"provenance": raw["provenance"], "entries": raw["entries"]})
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="crosses splits"):
        load_manifest(project)
    raw["entries"][1]["family"] = "new"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="hash mismatch"):
        load_manifest(project)


def test_reference_overlay_and_hidden_path_security(project):
    manifest = load_manifest(project)
    entry = manifest.entries[0]
    ref = project / "benchmark/references" / f"{entry.id}.json"
    ref.write_text(json.dumps({"../outside.py": "unsafe"}))
    with pytest.raises(ValueError, match="allowlist"):
        resolve_entry(project, entry, references=True)
    # Optimization/preflight never open reference files.
    resolve_entry(project, entry, references=False)


def test_fair_paired_runner_and_synthetic_separation(project):
    captured = []
    runner = BenchmarkRunner(
        project,
        settings(conditions=["static", "reflection"], attempts=2),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(captured),
    )
    summary = runner.run(task_ids=["task_001", "task_004"])
    data = runner.state.experiment(summary["experiment_id"])
    assert summary["status"] == "finished" and summary["synthetic"]
    assert len(data["cells"]) == 8
    assert summary["usage"]["api_calls"] == 16
    assert len({config.params.model_dump_json() for _, _, config, _ in captured}) == 1
    assert len({config.tools.model_dump_json() for _, _, config, _ in captured}) == 1
    for _, directory, _, _ in captured:
        assert not (directory / "reference.json").exists()
        assert not (directory / "repo" / "hidden.py").exists()
        assert directory.is_relative_to(runner.directory)
    assert not (project / "artifacts/benchmark/real").exists()
    paired = exploratory(data["cells"], "static", "reflection")
    assert paired["task_count"] == 2 and paired["paired_attempts"] == 4
    assert paired["promotion"] is False and paired["inconclusive"]
    assert paired["task_average_pass_rate_delta"] == 1.0


def test_runner_budget_and_partial_records(project):
    runner = BenchmarkRunner(
        project,
        settings(max_api_calls=1),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(),
    )
    summary = runner.run(task_ids=["task_001", "task_004"])
    data = runner.state.experiment(summary["experiment_id"])
    assert summary["status"] == "budget_exhausted"
    assert sorted(c["status"] for c in data["cells"]) == ["budget_exhausted", "pending"]
    assert summary["usage"]["api_calls"] == 1


def test_interruption_safe_records_and_recovery(project):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    runner = BenchmarkRunner(
        project, settings(), synthetic=True, client=SyntheticAPI(), runner=interrupted
    )
    with pytest.raises(KeyboardInterrupt):
        runner.run(task_ids=["task_001"])
    with runner.state.connect() as db:
        row = db.execute("SELECT id,status FROM experiments").fetchone()
    assert row["status"] == "interrupted"
    assert runner.state.cells(row["id"])[0]["status"] == "interrupted"
    runner.state.recover()
    assert runner.state.cells(row["id"])[0]["status"] == "interrupted"


def test_infrastructure_is_not_counted_as_coding_failure():
    result = RunResult(
        run_id="r",
        task_id="task_001",
        config_version="v",
        model="m",
        termination="sandbox_error",
        evaluation="sandbox_error",
    ).model_dump()
    assert classify(result) == "infrastructure_failure"
    summary = aggregate([{"status": "infrastructure_failure", "result": result}])
    assert summary["infrastructure_failures"] == 1 and summary["evaluated"] == 0
    assert summary["success_rate"] is None


def test_exploratory_clusters_repeats_and_does_not_promote(project):
    runner = BenchmarkRunner(
        project,
        settings(conditions=["static", "reflection"], attempts=3),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(),
    )
    summary = runner.run(task_ids=["task_001"])
    cells = runner.state.cells(summary["experiment_id"])
    first = exploratory(cells, "static", "reflection")
    assert first == exploratory(list(reversed(cells)), "static", "reflection")
    assert first["task_count"] == 1 and first["paired_attempts"] == 3
    assert first["inconclusive"] and first["promotion"] is False
    assert not (project / "artifacts/optimization/real/active.json").exists()


def test_spending_cap_requires_only_used_worker_pricing():
    with pytest.raises(ValueError, match="pricing"):
        settings(max_usd=0.1)
    limits = settings(max_usd=0.1, worker_prices=(1.0, 2.0))
    estimate = preflight(limits, 2)
    assert estimate["scheduled_runs"] == 2 and estimate["paid_requests_made"] is False
    assert estimate["max_http_calls_including_counting"] <= limits.max_api_calls
    assert estimate["potential_usd_upper_bound"] is not None


def test_final_flag_and_subset_validation(project):
    runner = BenchmarkRunner(
        project,
        settings(split="test"),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(),
    )
    with pytest.raises(ValueError, match="--final"):
        runner.run(task_ids=["task_003"])
    with pytest.raises(ValueError, match="subset"):
        runner.run(task_ids=["task_001"], final=True)


def test_meta_condition_requires_real_accepted_provenance(project):
    runner = BenchmarkRunner(
        project,
        settings(conditions=["static", "meta"]),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(),
    )
    with pytest.raises(ValueError, match="optimized-version"):
        runner.run(task_ids=["task_001"])
    with pytest.raises(ValueError, match="accepted"):
        runner.run(task_ids=["task_001"], optimized_version="f" * 64)


def test_runner_never_loads_private_reference_overlay(project):
    for path in (project / "benchmark/references").glob("*.json"):
        path.write_text("POISONED PRIVATE DATA NOT FOR WORKER EXECUTION")
    runner = BenchmarkRunner(
        project, settings(), synthetic=True, client=SyntheticAPI(), runner=mocked_runner()
    )
    assert runner.run(task_ids=["task_001"])["status"] == "finished"


def test_no_billable_http_allowed_by_suite():
    import httpx

    with httpx.Client() as client, pytest.raises(AssertionError, match="forbidden"):
        client.get("https://api.openai.com/v1/models")


def test_cli_preflight_and_dry_run_make_no_live_calls(project, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("live SDK/Docker constructor")

    monkeypatch.setattr("reflexforge.benchmark.runner.openai.OpenAI", forbidden)
    monkeypatch.setattr("reflexforge.benchmark.runner.docker.from_env", forbidden)
    runner = CliRunner()
    pre = runner.invoke(
        app, ["benchmark", "preflight", "--root", str(project), "--tasks", "task_001"]
    )
    assert pre.exit_code == 0 and not json.loads(pre.output)["paid_requests_made"]
    plan = runner.invoke(
        app, ["benchmark", "run", "--root", str(project), "--tasks", "task_001", "--dry-run"]
    )
    assert plan.exit_code == 0
    result = json.loads(plan.output)
    assert result["synthetic"] and result["status"] == "planned"
    state = BenchmarkState(project / "artifacts/benchmark/synthetic")
    assert all(c["result"] is None for c in state.cells(result["experiment_id"]))


def test_pending_and_synthetic_reports_are_separate(project):
    from reflexforge.analysis.reports import create_report

    pending = create_report(project)
    text = pending.read_text()
    assert "Pending: no API-backed benchmark" in text
    summary = json.loads((pending.parent / "summary.json").read_text())
    assert summary["by_condition"] == {} and summary["comparisons"] == []
    assert (pending.parent / "success.png").is_file()
    runner = BenchmarkRunner(
        project,
        settings(conditions=["static", "reflection"]),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(),
    )
    run = runner.run(task_ids=["task_001"])
    report = create_report(project, run["experiment_id"], synthetic=True)
    assert "synthetic demonstration" in report.read_text()
    data = json.loads((report.parent / "summary.json").read_text())
    assert data["by_condition"]["reflection"]["solved"] == 1
    assert data["overall_api_usage"]["http_calls"] == 4
    assert data["comparisons"][0]["promotion"] is False
    with pytest.raises(ValueError, match="unknown"):
        create_report(project, run["experiment_id"], synthetic=False)


def test_meta_condition_uses_versioned_snapshot_with_identical_budgets(project):
    from reflexforge.meta.schemas import Proposal
    from reflexforge.meta.versioning import VersionStore, candidate_snapshot
    from reflexforge.worker.config import AgentConfig

    manifest = load_manifest(project)
    store = VersionStore(project / "artifacts/optimization/real")
    original = AgentConfig.load(project / "config")
    base = store.commit(project / "config", {"kind": "baseline"}, None)
    proposal = Proposal(
        target_file="config/system_prompt.md",
        change_type="modify_prompt",
        hypothesis="Unit-test configuration",
        justification="Mocked accepted history",
        proposed_content=original.system_prompt + "\nValidate regressions carefully.\n",
    )
    candidate_snapshot(project / "config", project / "candidate", proposal)
    version = store.commit(
        project / "candidate",
        {
            "kind": "accepted",
            "synthetic": False,
            "bank_version": manifest.version,
            "worker_model": "worker-test",
        },
        base,
    )
    captured = []
    runner = BenchmarkRunner(
        project,
        settings(conditions=["static", "reflection", "meta"]),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(captured),
    )
    summary = runner.run(task_ids=["task_001"], optimized_version=version)
    data = runner.state.experiment(summary["experiment_id"])
    assert len(data["cells"]) == 3
    assert data["settings"]["source_versions"]["meta"] == version
    assert len({config.params.model_dump_json() for _, _, config, _ in captured}) == 1
    assert data["settings"]["sampling"]["temperature"] == 0.0
    assert data["settings"]["sampling"]["reasoning_effort"] == "none"


def test_optimizer_only_loads_selected_train_dev_contracts(project, monkeypatch):
    from reflexforge.meta.optimizer import freeze_tasks
    from reflexforge.meta.schemas import OptimizationSettings

    version = load_manifest(project).version
    limits = OptimizationSettings(
        worker_model="worker-test",
        meta_model="meta-test",
        benchmark_version=version,
        train_task_ids=["task_001", "task_004"],
        dev_task_ids=["task_002", "task_021"],
    )
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        if "/tasks/test/" in str(path) or "/benchmark/references/" in str(path):
            raise AssertionError("optimizer accessed held-out or private reference source")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    bank = freeze_tasks(project, project / "frozen", limits)
    assert [t.id for t, _ in bank["train"]] == ["task_001", "task_004"]
    assert [t.id for t, _ in bank["dev"]] == ["task_002", "task_021"]
    assert not (project / "frozen/test").exists()
    limits.benchmark_version = "incorrect"
    with pytest.raises(ValueError, match="mismatch"):
        freeze_tasks(project, project / "other", limits)


def test_optimize_pilot_preflight_is_small_and_zero_spend(project, monkeypatch):
    for name in (
        "REFLEXFORGE_INPUT_PRICE",
        "REFLEXFORGE_OUTPUT_PRICE",
        "REFLEXFORGE_META_INPUT_PRICE",
        "REFLEXFORGE_META_OUTPUT_PRICE",
    ):
        monkeypatch.setenv(name, "1.0")

    def forbidden(*args, **kwargs):
        raise AssertionError("live constructor in preflight")

    monkeypatch.setattr("reflexforge.meta.optimizer.openai.OpenAI", forbidden)
    monkeypatch.setattr("reflexforge.meta.optimizer.docker.from_env", forbidden)
    response = CliRunner().invoke(
        app,
        [
            "optimize",
            "--root",
            str(project),
            "--preset",
            "pilot",
            "--iterations",
            "1",
            "--max-usd",
            "0.1",
            "--preflight-only",
        ],
    )
    assert response.exit_code == 0
    data = json.loads(response.output)
    assert data["paid_requests_made"] is False
    assert len(data["settings"]["train_task_ids"]) == 2
    assert len(data["settings"]["dev_task_ids"]) == 2
    assert data["settings"]["execution_budget"]["max_tokens"] == 6000


def test_exploratory_refuses_mixed_models_and_duplicate_cells(project):
    runner = BenchmarkRunner(
        project,
        settings(conditions=["static", "reflection"]),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(),
    )
    summary = runner.run(task_ids=["task_001"])
    cells = runner.state.cells(summary["experiment_id"])
    with pytest.raises(ValueError, match="duplicate"):
        exploratory(cells + [cells[0]], "static", "reflection")
    cells[0]["result"]["model"] = "incompatible-model"
    with pytest.raises(ValueError, match="mismatch"):
        exploratory(cells, "static", "reflection")


def test_legacy_agent_exposure_is_not_claimed_as_fresh_held_out_data():
    manifest = load_manifest(ROOT)
    assert {e.id for e in manifest.entries if e.prior_agent_exposure} == {
        "task_001",
        "task_002",
        "task_003",
    }
    assert (
        len([e for e in manifest.entries if e.split == "test" and not e.prior_agent_exposure]) == 7
    )


def test_incomplete_pairing_remains_inconclusive(project):
    runner = BenchmarkRunner(
        project,
        settings(conditions=["static", "reflection"]),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(),
    )
    run = runner.run(task_ids=["task_001", "task_004"])
    cells = runner.state.cells(run["experiment_id"])
    cells[0]["result"] = None
    cells[0]["status"] = "pending"
    comparison = exploratory(cells, "static", "reflection")
    assert comparison["inconclusive"] and comparison["omitted_pairs"] == 1
