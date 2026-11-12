import json
import uuid
from pathlib import Path

import typer

from reflexforge.benchmark.manifest import load_manifest, resolve_entry
from reflexforge.benchmark.settings import BenchmarkSettings, optimization_settings, preflight
from reflexforge.benchmark.storage import BenchmarkState
from reflexforge.benchmark.suites import benchmark_artifacts, dataset_root
from reflexforge.settings import PROJECT_ROOT

app = typer.Typer(no_args_is_help=True, help="Versioned fixtures and bounded baseline experiments.")


@app.command("posthoc-evaluate")
def posthoc_evaluate(
    experiment: str,
    run_id: str,
    root: Path = PROJECT_ROOT,
) -> None:
    """Evaluate trace-reconstructed edits offline; preserve original experiment records."""
    from reflexforge.benchmark.posthoc import evaluate_recovery

    result = evaluate_recovery(root.resolve(), experiment, run_id)
    typer.echo(json.dumps(result, indent=2))
    if result["status"] != "passed" or not result["source_records_unchanged"]:
        raise typer.Exit(1)


def selected_entries(root, split, tasks, version=None, suite="debug"):
    data = dataset_root(root, suite)
    manifest = load_manifest(data, version)
    ids = tasks.split(",") if tasks else None
    entries = [e for e in manifest.entries if e.split == split and (ids is None or e.id in ids)]
    if not entries or ids and set(ids) != {e.id for e in entries}:
        raise typer.BadParameter("unknown task subset or split")
    for entry in entries:
        resolve_entry(data, entry)  # No reference fixes are loaded for a worker run or preflight.
    return manifest, entries


def settings_for(split, conditions, attempts, max_api_calls, max_tokens, max_usd, suite="debug"):
    base = optimization_settings(
        max_api_calls=max_api_calls, max_tokens=max_tokens, max_usd=None, suite=suite
    )
    values = base.model_dump()
    values["max_usd"] = max_usd
    values.pop("worker_temperature", None)
    values.pop("worker_reasoning_effort", None)
    if suite == "repobench":
        from reflexforge.schema import Budget

        values["run_budget"] = Budget(
            max_steps=20,
            max_tokens=24000,
            response_tokens=2048,
            wall_seconds=240,
            command_seconds=30,
            retry_limit=0,
        )
    return BenchmarkSettings(
        **values, split=split, conditions=conditions.split(","), attempts=attempts
    )


@app.command("list")
def list_benchmark(root: Path = PROJECT_ROOT, suite: str = "debug") -> None:
    from reflexforge.analysis.reports import benchmark_inventory

    inventory = benchmark_inventory(root, suite=suite)
    typer.echo(json.dumps(inventory, indent=2))


@app.command("validate")
def validate(
    root: Path = PROJECT_ROOT,
    tasks: str | None = None,
    workers: int = 2,
    structure_only: bool = False,
    suite: str = "debug",
) -> None:
    from reflexforge.benchmark.manifest import inspect_bank
    from reflexforge.benchmark.validation import validate_benchmark

    data = dataset_root(root, suite)
    manifest = load_manifest(data)
    if structure_only:
        inspection = inspect_bank(data, manifest)
        typer.echo(json.dumps({k: v for k, v in inspection.items() if k != "tasks"}, indent=2))
        return
    if workers < 1 or workers > 4:
        raise typer.BadParameter("workers must be 1..4")
    report = validate_benchmark(
        data.resolve(),
        manifest,
        selected=tasks.split(",") if tasks else None,
        workers=workers,
        artifacts=benchmark_artifacts(root.resolve(), suite),
    )
    typer.echo(
        json.dumps(
            {
                "version": report["version"],
                "valid": report["valid_count"],
                "selected": report["selected_count"],
            },
            indent=2,
        )
    )
    if report["valid_count"] != report["selected_count"]:
        raise typer.Exit(1)


@app.command("preflight")
def inspect_preflight(
    root: Path = PROJECT_ROOT,
    split: str = "train",
    tasks: str | None = None,
    conditions: str = "static",
    attempts: int = 1,
    max_api_calls: int = 40,
    max_tokens: int = 30000,
    max_usd: float | None = None,
    bank_version: str | None = None,
    suite: str = "debug",
) -> None:
    manifest, entries = selected_entries(root, split, tasks, bank_version, suite)
    settings = settings_for(split, conditions, attempts, max_api_calls, max_tokens, max_usd, suite)
    typer.echo(
        json.dumps(
            {
                "suite": suite,
                "bank_version": manifest.version,
                "tasks": [e.id for e in entries],
                "previously_exposed_task_ids": [e.id for e in entries if e.prior_agent_exposure],
                **preflight(settings, len(entries)),
            },
            indent=2,
        )
    )


@app.command("run")
def run(
    root: Path = PROJECT_ROOT,
    split: str = "train",
    tasks: str | None = None,
    config: str = "baseline",
    conditions: str = "static",
    attempts: int = 1,
    max_api_calls: int = 40,
    max_tokens: int = 30000,
    max_usd: float | None = None,
    bank_version: str | None = None,
    suite: str = "debug",
    optimized_version: str | None = None,
    final: bool = False,
    dry_run: bool = False,
    candidate_config: Path | None = None,
) -> None:
    from reflexforge.benchmark.runner import BenchmarkRunner

    manifest, entries = selected_entries(root, split, tasks, bank_version, suite)
    settings = settings_for(split, conditions, attempts, max_api_calls, max_tokens, max_usd, suite)
    path = root / "config" if config == "baseline" else root / config
    if split == "test" and not final:
        raise typer.BadParameter("held-out evaluation requires --final")
    if dry_run:
        # Plan only: never invent synthetic coding outcomes or construct an API client.
        state = BenchmarkState(benchmark_artifacts(root, suite) / "synthetic")
        experiment_id = uuid.uuid4().hex
        metadata = {
            "suite": suite,
            "bank_version": manifest.version,
            "entries": [e.model_dump() for e in entries],
            "settings": settings.model_dump(mode="json"),
            "preflight": preflight(settings, len(entries)),
            "synthetic": True,
            "source": str(path),
            "results": "pending; no worker or evaluator executed",
        }
        with state.connect() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?, 1, ?, ?)",
                (experiment_id, json.dumps(metadata), "planned"),
            )
            for entry in entries:
                for attempt in range(attempts):
                    for condition in settings.conditions:
                        db.execute(
                            "INSERT INTO benchmark_cells VALUES (?, ?, ?, ?, ?, NULL)",
                            (experiment_id, entry.id, attempt, condition, "pending"),
                        )
        typer.echo(
            json.dumps(
                {
                    "experiment_id": experiment_id,
                    "synthetic": True,
                    "status": "planned",
                    **metadata["preflight"],
                },
                indent=2,
            )
        )
        return
    result = BenchmarkRunner(root, settings).run(
        task_ids=[e.id for e in entries],
        config_path=path,
        optimized_version=optimized_version,
        bank_version=manifest.version,
        final=final,
        candidate_config_path=(root / candidate_config) if candidate_config is not None else None,
    )
    typer.echo(json.dumps(result, indent=2))
    if result["status"] != "finished":
        raise typer.Exit(1)


@app.command("report")
def report(
    experiment: str | None = None,
    root: Path = PROJECT_ROOT,
    synthetic: bool = False,
    suite: str = "debug",
) -> None:
    from reflexforge.analysis.reports import create_report

    typer.echo(str(create_report(root, experiment, synthetic=synthetic, suite=suite)))


@app.command("compare")
def compare_experiment(
    experiment: str, root: Path = PROJECT_ROOT, synthetic: bool = False, suite: str = "debug"
) -> None:
    from reflexforge.benchmark.statistics import exploratory

    state = BenchmarkState(
        benchmark_artifacts(root, suite) / ("synthetic" if synthetic else "real")
    )
    data = state.experiment(experiment)
    if bool(data["synthetic"]) != synthetic:
        raise typer.BadParameter("experiment provenance mismatch")
    conditions = data["settings"]["settings"]["conditions"]
    typer.echo(
        json.dumps(
            [
                exploratory(data["cells"], "static", condition)
                for condition in conditions
                if condition != "static"
            ],
            indent=2,
        )
    )
