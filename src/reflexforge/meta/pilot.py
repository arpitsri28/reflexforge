"""One grounded proposal, paired dev evaluation, no publication or promotion."""

import json
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import openai

from reflexforge.benchmark.manifest import load_manifest
from reflexforge.benchmark.runner import BenchmarkRunner
from reflexforge.benchmark.settings import BenchmarkSettings, preflight
from reflexforge.benchmark.statistics import exploratory
from reflexforge.benchmark.suites import dataset_root, optimization_artifacts
from reflexforge.meta.budget import BudgetedClient, BudgetExceeded, UsageLedger
from reflexforge.meta.diagnostics import GenerationDiagnostics
from reflexforge.meta.proposer import Proposer
from reflexforge.meta.reflector import Reflector, reflection_policy
from reflexforge.meta.reuse import select_training_failures
from reflexforge.meta.state import OptimizationState, atomic_json, exclusive_lock
from reflexforge.meta.versioning import candidate_snapshot
from reflexforge.worker.config import AgentConfig


def plan_pilot(
    root: Path,
    settings: BenchmarkSettings,
    config_path: Path,
    *,
    run_ids: list[str],
    experiment_ids: list[str],
    dev_tasks: list[str],
) -> tuple[dict, Any]:
    if (
        settings.suite != "repobench"
        or settings.split != "dev"
        or settings.conditions != ["static", "candidate"]
    ):
        raise ValueError("pilot requires RepoBench dev static/candidate conditions")
    if settings.max_usd is None or settings.meta_prices is None or settings.worker_prices is None:
        raise ValueError("pilot requires a USD cap and explicit worker AND meta pricing")
    manifest = load_manifest(dataset_root(root, settings.suite), settings.benchmark_version)
    if (
        not dev_tasks
        or len(set(dev_tasks)) != len(dev_tasks)
        or not set(dev_tasks) <= {e.id for e in manifest.entries if e.split == "dev"}
    ):
        raise ValueError("select explicit development task IDs only")
    selected = select_training_failures(
        root, settings, config_path, run_ids=run_ids, experiment_ids=experiment_ids
    )
    plan = {
        "reflection_policy": reflection_policy(),
        "suite": "repobench",
        "bank_version": manifest.version,
        "promotion": False,
        "paid_requests_made": False,
        "source_runs": selected.sources,
        "dev_tasks": dev_tasks,
        "settings": settings.model_dump(mode="json"),
        "baseline_config_version": AgentConfig.load(config_path).version,
        "worker_bound": preflight(settings, len(dev_tasks)),
        "meta_generation_limit": 2,
        "training_worker_reruns": 0,
        "max_http_calls_including_meta_and_counting": min(
            settings.max_api_calls,
            len(dev_tasks) * settings.attempts * 4 * settings.run_budget.max_steps + 4,
        ),
        "overall_token_limit": settings.max_tokens,
        "tokens_available_for_meta_after_full_worker_allocations": settings.max_tokens
        - len(dev_tasks) * settings.attempts * 2 * settings.run_budget.max_tokens,
        "uncapped_http_calls_including_meta_and_counting": len(dev_tasks)
        * settings.attempts
        * 4
        * settings.run_budget.max_steps
        + 4,
        "hard_usd_cap": settings.max_usd,
        "potential_usd_upper_bound": settings.max_tokens
        * max(*settings.worker_prices, *settings.meta_prices)
        / 1e6,
        "reflection_evidence": [
            {"run_id": f.run_id, "retained_events": len(f.events), "warnings": f.warnings}
            for f in selected.failures
        ],
        "warning": "Meta and both worker conditions share caps; caps can prevent completion. No strict promotion is possible with four dev tasks.",
    }
    return plan, selected


def run_pilot(
    root: Path,
    settings: BenchmarkSettings,
    config_path: Path,
    *,
    run_ids: list[str],
    experiment_ids: list[str],
    dev_tasks: list[str],
    synthetic: bool = False,
    client: Any = None,
    runner: Callable | None = None,
) -> dict:
    if runner is not None and not synthetic or synthetic and (client is None or runner is None):
        raise ValueError("mock execution requires explicit synthetic client and runner")
    plan, selected = plan_pilot(
        root,
        settings,
        config_path,
        run_ids=run_ids,
        experiment_ids=experiment_ids,
        dev_tasks=dev_tasks,
    )
    directory = (
        optimization_artifacts(root, "repobench")
        / "pilots"
        / ("synthetic" if synthetic else "real")
    )
    with exclusive_lock(directory):
        state = OptimizationState(directory)
        state.recover()  # Mark prior interrupted requests uncertain; never replay paid work.
        pilot_id = uuid.uuid4().hex
        work = directory / pilot_id
        work.mkdir(parents=True)
        shutil.copytree(config_path, work / "incumbent")
        config = AgentConfig.load(work / "incumbent")
        if config.version != plan["baseline_config_version"]:
            raise ValueError("source configuration changed since preflight")
        plan.update(synthetic=synthetic, pilot_id=pilot_id)
        atomic_json(work / "plan.json", plan)
        # Exact bounded payload retained for audit, without evaluator events or reports.
        atomic_json(
            work / "reflection-input.json", {"failures": [asdict(f) for f in selected.failures]}
        )
        with state.connect() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?, ?, ?, ?)",
                (pilot_id, int(synthetic), json.dumps(plan), "running"),
            )
        ledger = UsageLedger(state, pilot_id, settings)
        api = None
        benchmark = None
        audit = {
            "pilot_id": pilot_id,
            "synthetic": synthetic,
            "promotion": False,
            "plan": plan,
            "status": "running",
        }

        def save():
            atomic_json(work / "audit.json", state.trace.sanitize(audit))

        save()
        try:
            api = client if client is not None else openai.OpenAI(max_retries=0)
            meta = BudgetedClient(api, ledger, "meta", settings.meta_model, settings.meta_prices)
            diagnostics = GenerationDiagnostics(
                work / "diagnostics" / "reflector-attempt-001",
                pilot_id=pilot_id,
                generation_attempt=1,
                accounting=ledger.summary,
                prices=settings.meta_prices,
            )
            audit["reflector_diagnostics"] = str(diagnostics.directory)
            save()
            reflection = Reflector(meta, settings.meta_model, settings.meta_output_tokens).analyze(
                selected.failures, config, diagnostics=diagnostics
            )
            audit["reflection"] = reflection.model_dump()
            save()
            if not reflection.diagnoses:
                audit["status"] = "inconclusive"
                audit["reason"] = "insufficient_training_evidence"
            else:
                # No human report, manual hypotheses, dev feedback or prior pilot outcomes.
                proposal = Proposer(meta, settings.meta_model, settings.meta_output_tokens).propose(
                    config, reflection, []
                )
                audit["proposal"] = proposal.model_dump()
                save()  # Preserve rejected/invalid proposals too.
                candidate = candidate_snapshot(work / "incumbent", work / "candidate-tmp", proposal)
                candidate_dir = work / "candidates" / candidate.version / "config"
                candidate_dir.parent.mkdir(parents=True)
                (work / "candidate-tmp").rename(candidate_dir)
                audit["candidate_version"] = candidate.version
                audit["candidate_path"] = str(candidate_dir)
                save()
                benchmark = BenchmarkRunner(
                    root,
                    settings,
                    synthetic=synthetic,
                    client=api,
                    runner=runner,
                    shared_ledger=ledger,
                )
                result = benchmark.run(
                    task_ids=dev_tasks,
                    config_path=work / "incumbent",
                    candidate_config_path=candidate_dir,
                    bank_version=plan["bank_version"],
                )
                audit["benchmark"] = result
                cells = benchmark.state.cells(result["experiment_id"])
                audit["evaluation_outcomes"] = cells
                audit["comparison"] = exploratory(cells, "static", "candidate")
                audit["status"] = result["status"]
        except BaseException as exc:
            audit["status"] = (
                "interrupted"
                if isinstance(exc, (KeyboardInterrupt, SystemExit))
                else "budget_exhausted"
                if isinstance(exc, BudgetExceeded)
                else "failed"
            )
            audit["error_type"] = type(exc).__name__
            if hasattr(exc, "details"):
                audit["validation_error"] = exc.details
            if isinstance(exc, ValueError):
                audit["error"] = str(exc)[:1000]
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        finally:
            if benchmark is not None and "evaluation_outcomes" not in audit:
                # BenchmarkRunner persists partial cells even on Ctrl-C or controller errors.
                with benchmark.state.connect() as db:
                    rows = db.execute("SELECT id,settings FROM experiments").fetchall()
                matches = [
                    r["id"]
                    for r in rows
                    if json.loads(r["settings"]).get("shared_budget_experiment_id") == pilot_id
                ]
                if matches:
                    audit["benchmark_experiment_id"] = matches[-1]
                    audit["evaluation_outcomes"] = benchmark.state.cells(matches[-1])
                    audit["comparison"] = exploratory(
                        audit["evaluation_outcomes"], "static", "candidate"
                    )
            audit["usage"] = ledger.summary()
            save()
            with state.connect() as db:
                db.execute(
                    "UPDATE experiments SET status=? WHERE id=?", (audit["status"], pilot_id)
                )
            if client is None and api is not None:
                api.close()
        return {
            "pilot_id": pilot_id,
            "status": audit["status"],
            "synthetic": synthetic,
            "promotion": False,
            "audit": str(work / "audit.json"),
            "usage": audit["usage"],
        }
