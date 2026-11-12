"""RepoBench contracts and mocked integration; fixture Python never runs on host."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import ROOT
from test_benchmark import mocked_runner
from typer.testing import CliRunner

from reflexforge.benchmark.cli import settings_for
from reflexforge.benchmark.manifest import (
    inspect_bank,
    load_manifest,
    load_specification,
    resolve_entry,
)
from reflexforge.benchmark.runner import BenchmarkRunner
from reflexforge.benchmark.settings import BenchmarkSettings
from reflexforge.benchmark.statistics import exploratory
from reflexforge.benchmark.suites import benchmark_artifacts, dataset_root, optimization_artifacts
from reflexforge.cli import app
from reflexforge.meta.demo import SyntheticAPI
from reflexforge.meta.optimizer import freeze_tasks
from reflexforge.meta.schemas import OptimizationSettings
from reflexforge.tasks import fixture_files

DATA = ROOT / "suites/repobench"
MANIFEST = load_manifest(DATA)


@pytest.fixture
def repo_project(tmp_path):
    shutil.copytree(DATA / "tasks", tmp_path / "suites/repobench/tasks")
    shutil.copytree(DATA / "benchmark", tmp_path / "suites/repobench/benchmark")
    shutil.copytree(ROOT / "config", tmp_path / "config")
    return tmp_path


@pytest.mark.parametrize("entry", MANIFEST.entries, ids=lambda entry: entry.id)
def test_independent_docker_qa_receipts(entry):
    report = json.loads((DATA / "benchmark/validation.json").read_text())
    assert report["version"] == MANIFEST.version
    row = next(row for row in report["results"] if row["task_id"] == entry.id)
    spec = load_specification(DATA, MANIFEST)[entry.id]
    assert row["manifest_hash"] == MANIFEST.version
    assert row["source_hash"] == entry.source_hash
    assert row["reference_hash"] == entry.reference_hash
    assert row["mutant_hash"] == spec["mutant_hash"]
    assert all(
        row[key]
        for key in (
            "valid",
            "unmodified_rejected",
            "partial_fix_rejected",
            "reproducible",
            "hidden_test_isolation",
        )
    )
    assert row["buggy"]["visible_exit"] != 0
    assert row["reference"]["visible_exit"] == row["partial_fix"]["visible_exit"] == 0
    for label in ("buggy", "reference", "partial_fix"):
        assert row[label]["public_tests_run"] == spec["public_test_count"]
        for regression in row[label]["regressions"]:
            assert regression["tests_run"] == spec["hidden_test_count"]
            assert regression["successful"] is (label == "reference")
    task, directory, patch = resolve_entry(DATA, entry, references=True)
    public = fixture_files(task, directory)
    assert set(spec["module_roles"]) == set(task.editable)
    assert spec["meaningful_modules"] == len(task.editable) >= 5
    assert len(spec["dependency_path"]) >= 3
    assert spec["dependency_depth"] >= 1
    assert spec["empirical_difficulty"] is None
    assert set(patch) <= set(task.editable)
    assert not any("hidden" in name or "reference" in name for name in public)
    assert not any("root_cause" in content for content in public.values())


def test_suite_distribution_snapshot_and_original_bank_unchanged():
    report = inspect_bank(DATA, MANIFEST)
    assert report["split_counts"] == {"train": 6, "dev": 4, "test": 2}
    assert len(report["category_counts"]) == 12
    assert not report["near_duplicates"]
    snapshot = DATA / "versions" / MANIFEST.version
    archived = load_manifest(snapshot, MANIFEST.version)
    for entry in archived.entries:
        resolve_entry(snapshot, entry, references=True)
    assert load_manifest(ROOT).version == (
        "d47b31353fc8ee339a3d293dc88b1f6861b1c6febe5e4e48d525bb1d84790e94"
    )
    assert len(load_manifest(ROOT).entries) == 38


def test_private_specification_integrity_and_symlink(repo_project, tmp_path):
    data = dataset_root(repo_project, "repobench")
    spec = data / "benchmark/specification.json"
    original = spec.read_text()
    spec.write_text("{}")
    with pytest.raises(ValueError, match="specification hash"):
        inspect_bank(data, load_manifest(data))
    spec.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text(original)
    spec.symlink_to(outside)
    with pytest.raises(ValueError, match="path escapes"):
        load_specification(data, load_manifest(data))


def test_optimizer_freezes_only_selected_train_dev_without_private_explanations(
    repo_project, monkeypatch
):
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        text = str(path)
        if any(
            part in text
            for part in (
                "/tasks/test/",
                "/references/",
                "/mutants/",
                "/specification.json",
            )
        ):
            raise AssertionError("optimizer accessed held-out or private answer material")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    settings = OptimizationSettings(
        worker_model="worker-test",
        meta_model="meta-test",
        suite="repobench",
        benchmark_version=MANIFEST.version,
        train_task_ids=["task_101", "task_102"],
        dev_task_ids=["task_107", "task_108"],
    )
    bank = freeze_tasks(repo_project, repo_project / "frozen", settings)
    assert [task.id for task, _ in bank["train"]] == ["task_101", "task_102"]
    assert [task.id for task, _ in bank["dev"]] == ["task_107", "task_108"]
    assert not (repo_project / "frozen/test").exists()
    settings.train_task_ids = ["task_111"]
    with pytest.raises(ValueError, match="unknown optimization"):
        freeze_tasks(repo_project, repo_project / "invalid", settings)


def test_exploratory_candidate_paired_fixed_budget_without_promotion(repo_project):
    candidate = repo_project / "candidate"
    shutil.copytree(repo_project / "config", candidate)
    prompt = candidate / "system_prompt.md"
    prompt.write_text(prompt.read_text() + "\nInspect dependency contracts before editing.\n")
    captured = []
    settings = BenchmarkSettings(
        meta_model="meta-test",
        worker_model="worker-test",
        suite="repobench",
        split="dev",
        conditions=["static", "reflection", "candidate"],
    )
    runner = BenchmarkRunner(
        repo_project,
        settings,
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(captured),
    )
    result = runner.run(candidate_config_path=candidate)
    assert result["suite"] == "repobench" and result["status"] == "finished"
    data = runner.state.experiment(result["experiment_id"])
    assert data["settings"]["suite"] == "repobench"
    assert data["settings"]["bank_version"] == MANIFEST.version
    assert len(data["cells"]) == 12
    for cell in data["cells"]:
        result = cell["result"]
        assert result["suite"] == "repobench" and result["bank_version"] == MANIFEST.version
        assert result["execution_budget"] == settings.run_budget.model_dump()
        assert result["source_config_version"]
        assert result["model"] == "worker-test" and result["condition"] == cell["condition"]
    assert len({config.params.model_dump_json() for _, _, config, _ in captured}) == 1
    assert len({config.tools.model_dump_json() for _, _, config, _ in captured}) == 1
    comparison = exploratory(data["cells"], "static", "candidate")
    assert comparison["task_count"] == 4
    assert comparison["inconclusive"] and comparison["promotion"] is False
    assert runner.directory == benchmark_artifacts(repo_project, "repobench") / "synthetic"
    assert not (optimization_artifacts(repo_project, "repobench") / "real/active.json").exists()
    assert not (repo_project / "artifacts/benchmark/real").exists()


@pytest.mark.parametrize("invalid", ["missing", "budget", "tools"])
def test_candidate_requires_explicit_path_and_preserves_comparison_contract(repo_project, invalid):
    candidate = repo_project / "candidate"
    shutil.copytree(repo_project / "config", candidate)
    if invalid != "missing":
        path = candidate / ("params.yaml" if invalid == "budget" else "tools.yaml")
        values = yaml.safe_load(path.read_text())
        if invalid == "budget":
            values["max_steps"] += 1
        else:
            values["descriptions"]["read_file"] += " Changed description."
        path.write_text(yaml.safe_dump(values))
    runner = BenchmarkRunner(
        repo_project,
        BenchmarkSettings(
            meta_model="meta-test",
            worker_model="worker-test",
            suite="repobench",
            conditions=["candidate"],
        ),
        synthetic=True,
        client=SyntheticAPI(),
        runner=mocked_runner(),
    )
    with pytest.raises(ValueError):
        runner.run(
            task_ids=["task_101"], candidate_config_path=None if invalid == "missing" else candidate
        )


def test_cli_suite_preflight_plan_and_validation_are_zero_spend(repo_project, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("live constructor")

    monkeypatch.setattr("reflexforge.benchmark.runner.openai.OpenAI", forbidden)
    monkeypatch.setattr("reflexforge.benchmark.runner.docker.from_env", forbidden)
    cli = CliRunner()
    common = ["--root", str(repo_project), "--suite", "repobench"]
    for command in (
        ["benchmark", "validate", *common, "--structure-only"],
        ["benchmark", "preflight", *common, "--tasks", "task_101"],
        ["benchmark", "run", *common, "--tasks", "task_101", "--dry-run"],
    ):
        response = cli.invoke(app, command)
        assert response.exit_code == 0, response.output
        data = json.loads(response.output)
        assert data.get("paid_requests_made", False) is False
    settings = settings_for("train", "static", 1, 40, 24000, None, "repobench")
    assert settings.suite == "repobench" and settings.run_budget.max_tokens == 24000
    response = cli.invoke(app, ["benchmark", "run", *common, "--split", "test", "--dry-run"])
    assert response.exit_code != 0 and "--final" in response.output


def test_suite_validation_and_budget_caps():
    from reflexforge.benchmark.settings import preflight

    with pytest.raises(ValueError, match="suite"):
        dataset_root(ROOT, "unknown")
    with pytest.raises(ValueError):
        BenchmarkSettings(
            meta_model="meta-test",
            worker_model="worker-test",
            suite="repobench",
            conditions=["static", "static"],
        )
    settings = BenchmarkSettings(
        meta_model="meta-test",
        worker_model="worker-test",
        suite="repobench",
        max_api_calls=2,
        max_tokens=500,
        max_usd=0.01,
        worker_prices=(1, 2),
    )
    estimate = preflight(settings, 12)
    assert estimate["bounded_token_upper_limit"] == 500
    assert estimate["max_http_calls_including_counting"] == 2
    assert estimate["hard_usd_cap"] == 0.01


def test_suite_report_pending_and_active_config_isolation(repo_project):
    from reflexforge.analysis.reports import create_report
    from reflexforge.meta.versioning import VersionStore, active_config_path

    report = create_report(repo_project, suite="repobench")
    text = report.read_text()
    assert "repobench" in text and "Both RepoBench test repositories" in text
    assert "seven test fixtures" not in text
    assert json.loads((report.parent / "summary.json").read_text())["suite"] == "repobench"
    store = VersionStore(optimization_artifacts(repo_project, "repobench") / "real")
    version = store.commit(repo_project / "config", {"kind": "baseline"}, None)
    assert active_config_path(repo_project, "repobench") == store.snapshot(version)
    assert active_config_path(repo_project) == repo_project / "config"


def test_optimizer_repo_preflight_uses_suite_and_no_clients(repo_project, monkeypatch):
    for prefix in ("REFLEXFORGE_", "REFLEXFORGE_META_"):
        for suffix in ("INPUT_PRICE", "OUTPUT_PRICE"):
            monkeypatch.setenv(prefix + suffix, "1")
    response = CliRunner().invoke(
        app,
        [
            "optimize",
            "--root",
            str(repo_project),
            "--suite",
            "repobench",
            "--preset",
            "pilot",
            "--iterations",
            "1",
            "--max-usd",
            "0.1",
            "--preflight-only",
        ],
    )
    assert response.exit_code == 0, response.output
    data = json.loads(response.output)
    assert data["suite"] == "repobench" and data["bank_version"] == MANIFEST.version
    assert data["paid_requests_made"] is False
    assert data["settings"]["train_task_ids"] == ["task_101", "task_102"]
    assert data["settings"]["dev_task_ids"] == ["task_107", "task_108"]


def test_four_development_tasks_cannot_promote_even_with_repeated_perfect_wins():
    from reflexforge.evaluation.gatekeeper import PairedRun, compare
    from reflexforge.schema import RunResult

    ids = [entry.id for entry in MANIFEST.entries if entry.split == "dev"]
    pairs = []
    for task_id in ids:
        for repetition in range(3):
            runs = [
                RunResult(
                    run_id=f"{task_id}-{repetition}-{version}",
                    task_id=task_id,
                    config_version=version,
                    model="mock",
                    synthetic=True,
                    termination="completed",
                    evaluation=outcome,
                    input_tokens=100,
                    output_tokens=20,
                    wall_seconds=1,
                    tool_calls=2,
                )
                for version, outcome in (("base", "failed"), ("candidate", "passed"))
            ]
            pairs.append(PairedRun(task_id, repetition, *runs))
    decision = compare(pairs, ids, 3, "base", "candidate", "mock", True)
    assert decision["task_wins"] == 4 and decision["outcome"] == "inconclusive"
    assert decision["accepted"] is False
