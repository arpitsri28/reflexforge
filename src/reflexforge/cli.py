import json
import os
import platform
from pathlib import Path

import docker
import openai
import typer

from reflexforge.benchmark.cli import app as benchmark_app
from reflexforge.benchmark.suites import dataset_root
from reflexforge.meta.versioning import active_config_path
from reflexforge.orchestrator import run_worker
from reflexforge.settings import PROJECT_ROOT
from reflexforge.storage.database import Database
from reflexforge.tasks import fixture_files, load_tasks
from reflexforge.worker.agent import configured_model
from reflexforge.worker.config import AgentConfig

app = typer.Typer(
    no_args_is_help=True,
    help="ReflexForge coding-agent and configuration-optimization experiments.",
)
app.add_typer(benchmark_app, name="benchmark")


@app.command("meta-pilot")
def meta_pilot(
    root: Path = PROJECT_ROOT,
    run_ids: str | None = None,
    experiment_ids: str | None = None,
    dev_tasks: str = "task_107",
    config: Path = Path("config"),
    max_api_calls: int = 200,
    max_tokens: int = 200000,
    max_usd: float = 0.50,
    execute: bool = False,
) -> None:
    """Reuse verified training failures; default to zero-spend preflight."""
    from reflexforge.benchmark.cli import settings_for
    from reflexforge.meta.pilot import plan_pilot, run_pilot

    settings = settings_for(
        "dev", "static,candidate", 1, max_api_calls, max_tokens, max_usd, "repobench"
    )
    selection = {
        "run_ids": run_ids.split(",") if run_ids else [],
        "experiment_ids": experiment_ids.split(",") if experiment_ids else [],
        "dev_tasks": dev_tasks.split(","),
    }
    root = root.resolve()
    path = root / config
    if not execute:
        plan, _ = plan_pilot(root, settings, path, **selection)
        typer.echo(json.dumps(plan, indent=2))
        return
    result = run_pilot(root, settings, path, **selection)
    typer.echo(json.dumps(result, indent=2))
    if result["status"] not in {"finished", "inconclusive"}:
        raise typer.Exit(1)


@app.command()
def doctor(root: Path = PROJECT_ROOT, api: bool = False) -> None:
    """Readiness checks. --api only retrieves model metadata; no generation request."""
    checks: dict[str, object] = {"python": platform.python_version()}
    try:
        config = AgentConfig.load(active_config_path(root))
        tasks = load_tasks(root / "tasks")
        if not tasks:
            raise ValueError("no task fixtures found")
        for task, directory in tasks:
            fixture_files(task, directory)
            if not (directory / task.hidden_test).is_file():
                raise ValueError(f"missing evaluator test for {task.id}")
        checks.update(config=config.version, tasks=len(tasks))
    except Exception as exc:
        checks["configuration_error"] = str(exc)
    checks["api_key_configured"] = bool(os.getenv("OPENAI_API_KEY"))
    checks["model"] = configured_model()
    try:
        client = docker.from_env(timeout=3)
        try:
            client.ping()
            checks["docker"] = "ready"
            client.images.get(os.getenv("REFLEXFORGE_IMAGE", "reflexforge-sandbox:local"))
            checks["image"] = "ready"
        finally:
            client.close()
    except Exception as exc:
        checks["docker_or_image_error"] = str(exc)
    if api:
        try:
            with openai.OpenAI(max_retries=0, timeout=10) as client:
                client.models.retrieve(configured_model())
            checks["api"] = "connected"
        except Exception as exc:
            checks["api_error"] = type(exc).__name__
    typer.echo(json.dumps(checks, indent=2))
    if any(k.endswith("error") for k in checks):
        raise typer.Exit(1)


@app.command("list-tasks")
def list_tasks(root: Path = PROJECT_ROOT) -> None:
    for task, _ in load_tasks(root / "tasks"):
        typer.echo(f"{task.id}\t{task.split}\t{task.issue}")


@app.command("run-worker")
def worker(
    task: str = typer.Option(...),
    root: Path = PROJECT_ROOT,
    config: Path | None = None,
    dry_run: bool = False,
) -> None:
    matches = [(t, p) for t, p in load_tasks(root / "tasks") if t.id == task]
    if not matches:
        raise typer.BadParameter(f"unknown task: {task}")
    t, p = matches[0]
    result = run_worker(
        t,
        p,
        AgentConfig.load(root / config if config is not None else active_config_path(root)),
        root / "artifacts",
        dry_run=dry_run,
    )
    typer.echo(result.model_dump_json(indent=2))
    if not dry_run and result.evaluation != "passed":
        raise typer.Exit(1)


@app.command()
def evaluate(
    split: str = "train",
    root: Path = PROJECT_ROOT,
    config: Path | None = None,
    dry_run: bool = False,
    final: bool = False,
) -> None:
    if split not in {"train", "dev", "test"}:
        raise typer.BadParameter("split must be train, dev, or test")
    if split == "test" and not final and not dry_run:
        raise typer.BadParameter("held-out evaluation requires explicit --final")
    agent_config = AgentConfig.load(
        root / config if config is not None else active_config_path(root)
    )
    for task, directory in load_tasks(root / "tasks", split):
        result = run_worker(task, directory, agent_config, root / "artifacts", dry_run=dry_run)
        typer.echo(result.model_dump_json())


@app.command()
def report(root: Path = PROJECT_ROOT) -> None:
    """Show real run records only; no results are inferred from dry runs."""
    records = Database(root / "artifacts" / "experiments.sqlite3").results()
    typer.echo(json.dumps({"real_runs": len(records), "runs": records}, indent=2))


@app.command()
def optimize(
    root: Path = PROJECT_ROOT,
    iterations: int = 1,
    repetitions: int = 1,
    max_api_calls: int = 40,
    max_tokens: int = 100000,
    max_usd: float | None = None,
    dry_run: bool = False,
    scenario: str = "accept",
    preset: str = "full",
    bank_version: str | None = None,
    preflight_only: bool = False,
    suite: str = "debug",
) -> None:
    """Optimize on train/dev only. --dry-run uses explicitly synthetic outcomes."""
    from reflexforge.meta.demo import run_demo
    from reflexforge.meta.optimizer import Optimizer
    from reflexforge.meta.schemas import OptimizationSettings

    def prices(prefix: str) -> tuple[float, float] | None:
        first, second = os.getenv(prefix + "INPUT_PRICE"), os.getenv(prefix + "OUTPUT_PRICE")
        if not first or not second:
            return None
        return float(first), float(second)

    settings = OptimizationSettings(
        max_iterations=iterations,
        suite=suite,
        repetitions=repetitions,
        max_api_calls=max_api_calls,
        max_tokens=max_tokens,
        max_usd=max_usd,
        worker_model=configured_model(),
        meta_model=os.getenv("OPENAI_META_MODEL", "").strip() or configured_model(),
        worker_prices=prices("REFLEXFORGE_"),
        meta_prices=prices("REFLEXFORGE_META_"),
    )
    data_root = dataset_root(root, suite)
    if dry_run and suite != "debug":
        raise typer.BadParameter(
            "RepoBench supports benchmark --dry-run and optimize --preflight-only; legacy synthetic optimizer demos are debug-only"
        )
    if preset not in {"pilot", "full"}:
        raise typer.BadParameter("preset must be pilot or full")
    if (data_root / "benchmark" / "manifest.json").exists() and not dry_run:
        from reflexforge.benchmark.manifest import load_manifest
        from reflexforge.schema import Budget

        manifest = load_manifest(data_root, bank_version)
        settings.benchmark_version = manifest.version
        settings.worker_temperature = 0.0
        settings.worker_reasoning_effort = "none"
        if preset == "pilot":
            settings.train_task_ids = [e.id for e in manifest.entries if e.split == "train"][:2]
            settings.dev_task_ids = [e.id for e in manifest.entries if e.split == "dev"][:2]
            settings.execution_budget = Budget(
                max_steps=6, max_tokens=6000, response_tokens=1024, wall_seconds=90, retry_limit=0
            )
            if settings.max_usd is None:
                raise typer.BadParameter("pilot requires --max-usd and explicit pricing")
        if preflight_only:
            from reflexforge.benchmark.settings import optimization_preflight
            from reflexforge.worker.agent import effective_budget

            runtime_budget = AgentConfig.load(active_config_path(root, suite)).params
            if settings.execution_budget is not None:
                runtime_budget = effective_budget(runtime_budget, settings.execution_budget)
            bound = optimization_preflight(
                settings,
                len(settings.train_task_ids)
                if settings.train_task_ids is not None
                else sum(e.split == "train" for e in manifest.entries),
                len(settings.dev_task_ids)
                if settings.dev_task_ids is not None
                else sum(e.split == "dev" for e in manifest.entries),
                runtime_budget,
            )
            typer.echo(
                json.dumps(
                    {
                        **bound,
                        "bank_version": manifest.version,
                        "preset": preset,
                        "suite": suite,
                        "settings": settings.model_dump(mode="json"),
                        "warning": (
                            "Pilot cannot satisfy five-distinct-dev-task promotion; caps may stop before all stages."
                            if preset == "pilot"
                            else (
                                "RepoBench has four dev tasks; strict five-task promotion is unavailable."
                                if suite == "repobench"
                                else "Full dev sample can support strict promotion, but evidence and resources may still be insufficient."
                            )
                        ),
                    },
                    indent=2,
                )
            )
            return
    elif preflight_only:
        typer.echo(
            json.dumps({"paid_requests_made": False, "settings": settings.model_dump(mode="json")})
        )
        return
    result = (
        run_demo(root.resolve(), settings, scenario) if dry_run else Optimizer(root, settings).run()
    )
    typer.echo(json.dumps(result, indent=2))
    if result["status"] != "finished":
        raise typer.Exit(1)


@app.command("config-history")
def config_history(
    root: Path = PROJECT_ROOT, synthetic: bool = False, suite: str = "debug"
) -> None:
    from reflexforge.meta.optimizer import optimization_directory
    from reflexforge.meta.versioning import VersionStore

    store = VersionStore(optimization_directory(root, synthetic, suite))
    typer.echo(
        json.dumps(
            {
                "synthetic": synthetic,
                "suite": suite,
                "active": store.active()[0] if store.active() else None,
                "versions": store.history(),
            },
            indent=2,
        )
    )


@app.command()
def proposals(root: Path = PROJECT_ROOT, synthetic: bool = False, suite: str = "debug") -> None:
    from reflexforge.meta.optimizer import optimization_directory
    from reflexforge.meta.state import OptimizationState

    rows = OptimizationState(optimization_directory(root, synthetic, suite)).iterations()
    typer.echo(json.dumps([row for row in rows if "proposal" in row["data"]], indent=2))


@app.command("show-iteration")
def show_iteration(
    iteration_id: str, root: Path = PROJECT_ROOT, synthetic: bool = False, suite: str = "debug"
) -> None:
    from reflexforge.meta.optimizer import optimization_directory
    from reflexforge.meta.state import OptimizationState

    rows = OptimizationState(optimization_directory(root, synthetic, suite)).iterations()
    selected = [row for row in rows if row["id"] == iteration_id]
    if not selected:
        raise typer.BadParameter("unknown iteration id (check --synthetic)")
    typer.echo(json.dumps(selected[0], indent=2))


@app.command("rollback-config")
def rollback_config(
    version: str, root: Path = PROJECT_ROOT, synthetic: bool = False, suite: str = "debug"
) -> None:
    from reflexforge.meta.optimizer import optimization_directory
    from reflexforge.meta.state import exclusive_lock
    from reflexforge.meta.versioning import VersionStore

    directory = optimization_directory(root, synthetic, suite)
    with exclusive_lock(directory):
        VersionStore(directory).rollback(version)
    typer.echo(json.dumps({"active_version": version, "synthetic": synthetic}))


if __name__ == "__main__":
    app()
