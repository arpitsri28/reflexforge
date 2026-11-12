import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from reflexforge.benchmark.manifest import inspect_bank, load_manifest
from reflexforge.benchmark.statistics import aggregate, exploratory
from reflexforge.benchmark.storage import BenchmarkState
from reflexforge.benchmark.suites import benchmark_artifacts, dataset_root, optimization_artifacts
from reflexforge.meta.state import OptimizationState, atomic_json


def benchmark_inventory(root: Path, suite: str = "debug") -> dict[str, Any]:
    data = dataset_root(root, suite)
    manifest = load_manifest(data)
    inspection = inspect_bank(data, manifest)
    for entry in inspection["tasks"]:
        path = benchmark_artifacts(root, suite) / "qa" / manifest.version / f"{entry['id']}.json"
        qa = json.loads(path.read_text()) if path.exists() else {}
        entry["validation"] = (
            "valid"
            if qa.get("valid")
            and qa.get("source_hash") == entry["source_hash"]
            and qa.get("reference_hash") == entry["reference_hash"]
            else "pending"
        )
    return inspection


def create_report(
    root: Path, experiment_id: str | None = None, *, synthetic: bool = False, suite: str = "debug"
) -> Path:
    cache = root / "artifacts" / "benchmark" / "plot-cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory = benchmark_artifacts(root, suite) / ("synthetic" if synthetic else "real")
    state = BenchmarkState(directory)
    inventory = benchmark_inventory(root, suite=suite)
    experiment = state.experiment(experiment_id) if experiment_id else None
    if experiment and bool(experiment["synthetic"]) != synthetic:
        raise ValueError("report provenance mismatch")
    if experiment and experiment["settings"]["bank_version"] != inventory["version"]:
        raise ValueError("report task-bank version mismatch")
    cells = experiment["cells"] if experiment else []
    conditions = sorted({c["condition"] for c in cells})
    by_condition = {
        condition: aggregate([c for c in cells if c["condition"] == condition])
        for condition in conditions
    }
    metadata = {entry["id"]: entry for entry in inventory["tasks"]}

    def grouped(field):
        values = sorted({metadata[c["task_id"]][field] for c in cells})
        return {
            value: {
                condition: aggregate(
                    [
                        c
                        for c in cells
                        if c["condition"] == condition and metadata[c["task_id"]][field] == value
                    ]
                )
                for condition in conditions
            }
            for value in values
        }

    comparisons = [
        exploratory(cells, "static", condition) for condition in conditions if condition != "static"
    ]
    optimization_dir = optimization_artifacts(root, suite) / ("synthetic" if synthetic else "real")
    iterations = (
        OptimizationState(optimization_dir).iterations()
        if (optimization_dir / "optimization.sqlite3").exists()
        else []
    )
    iterations = [
        r
        for r in iterations
        if r["data"].get("conditions", {}).get("bank_version") == inventory["version"]
    ]
    output = directory / "reports" / (experiment_id or "pending")
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "suite": suite,
        "provenance": "synthetic demonstration" if synthetic else "real evaluations only",
        "bank_version": inventory["version"],
        "experiment_id": experiment_id,
        "split": experiment["settings"]["settings"]["split"] if experiment else None,
        "status": experiment["status"] if experiment else "pending",
        "previously_exposed_task_ids": [
            e["id"] for e in inventory["tasks"] if e["prior_agent_exposure"]
        ],
        "fresh_test_tasks_available": sum(
            e["split"] == "test" and not e["prior_agent_exposure"] for e in inventory["tasks"]
        ),
        "config_versions": experiment["settings"].get("config_versions", {}) if experiment else {},
        "source_config_versions": experiment["settings"].get("source_versions", {})
        if experiment
        else {},
        "by_condition": by_condition,
        "by_difficulty": grouped("difficulty"),
        "by_category": grouped("category"),
        "comparisons": comparisons,
        "optimization_history": [
            {"id": r["id"], "status": r["status"], "decision": r["data"].get("decision")}
            for r in iterations
            if bool(r["synthetic"]) == synthetic
        ],
        "training_failures": dict(
            Counter(
                (c["result"].get("failure_category") or "unclassified")
                for c in cells
                if c.get("result")
                and c["status"] == "coding_failure"
                and metadata[c["task_id"]]["split"] == "train"
            )
        ),
    }
    fresh_cells = [c for c in cells if not metadata[c["task_id"]]["prior_agent_exposure"]]
    summary["fresh_test_comparisons"] = (
        [
            exploratory(fresh_cells, "static", condition)
            for condition in conditions
            if condition != "static"
        ]
        if summary["split"] == "test"
        else []
    )
    summary["optimization_training_failures"] = dict(
        Counter(
            run.get("failure_category") or "unclassified"
            for iteration in iterations
            for run in iteration["data"].get("train_runs", [])
            if run.get("evaluation") == "failed"
        )
    )
    usage_rows = []
    if experiment_id:
        usage_state, usage_id = state, experiment_id
        shared_id = experiment["settings"].get("shared_budget_experiment_id")
        if shared_id:
            usage_state = OptimizationState(
                optimization_artifacts(root, suite)
                / "pilots"
                / ("synthetic" if synthetic else "real")
            )
            usage_id = shared_id
            summary["shared_budget_experiment_id"] = shared_id
            summary["api_usage_scope"] = "pilot meta calls plus development worker conditions"
        with usage_state.connect() as db:
            usage_rows = db.execute(
                "SELECT * FROM api_usage WHERE experiment_id=?", (usage_id,)
            ).fetchall()
    summary["overall_api_usage"] = {
        "http_calls": sum(r["calls"] for r in usage_rows),
        "tokens_including_unresolved_reservations": sum(r["tokens"] for r in usage_rows),
        "usd_upper_bound": sum(r["usd"] for r in usage_rows)
        if usage_rows and all(r["usd"] is not None for r in usage_rows)
        else None,
        "uncertain": any(r["state"] in {"unknown", "reserved", "overrun"} for r in usage_rows),
    }
    atomic_json(output / "summary.json", summary)

    def chart(name, title, labels=None, values=None):
        fig, ax = plt.subplots(figsize=(8, 4))
        if values:
            ax.bar(labels, values)
            ax.tick_params(axis="x", labelrotation=35)
        else:
            ax.text(
                0.5,
                0.5,
                "Pending: no measured data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
        ax.set_title(title + (" [SYNTHETIC]" if synthetic else ""))
        fig.tight_layout()
        fig.savefig(output / (name + ".png"), dpi=140)
        plt.close(fig)

    measured = [
        (k, v["success_rate"]) for k, v in by_condition.items() if v["success_rate"] is not None
    ]
    chart(
        "success", "Success rate by condition", [k for k, _ in measured], [v for _, v in measured]
    )
    for field in ("tokens_per_solved", "cost_per_solved"):
        values = [
            (condition, result[field])
            for condition, result in by_condition.items()
            if result[field] is not None
        ]
        chart(
            field, field.replace("_", " ").title(), [k for k, _ in values], [v for _, v in values]
        )
    for field, filename in [("by_difficulty", "difficulty"), ("by_category", "categories")]:
        values = [
            (f"{group}/{condition}", result["success_rate"])
            for group, items in summary[field].items()
            for condition, result in items.items()
            if result["success_rate"] is not None
        ]
        chart(filename, f"Success by {filename}", [k for k, _ in values], [v for _, v in values])
    for metric in ("wall_seconds", "tool_calls", "input_tokens", "output_tokens"):
        values = [c["result"][metric] for c in cells if c.get("result")]
        fig, ax = plt.subplots(figsize=(8, 4))
        if values:
            ax.hist(values, bins=min(12, len(values)))
        else:
            ax.text(0.5, 0.5, "Pending: no measured data", ha="center", transform=ax.transAxes)
        ax.set_title(metric + (" [SYNTHETIC]" if synthetic else ""))
        fig.tight_layout()
        fig.savefig(output / f"{metric}.png", dpi=140)
        plt.close(fig)
    history = summary["optimization_history"]
    chart(
        "acceptance",
        "Proposal decisions",
        list(Counter(r["status"] for r in history)),
        list(Counter(r["status"] for r in history).values()),
    )
    chart(
        "failures",
        "Training coding failure categories",
        list(summary["training_failures"]),
        list(summary["training_failures"].values()),
    )
    dev = [
        (r["id"], r["decision"]["candidate"]["pass_rate"])
        for r in history
        if r["decision"] and r["decision"]["candidate"]["pass_rate"] is not None
    ]
    chart("dev", "Candidate dev pass rate by iteration", [k for k, _ in dev], [v for _, v in dev])
    lines = [
        "# ReflexForge benchmark report",
        "",
        f"Provenance: **{summary['provenance']}**.",
        f"Suite: `{suite}`.",
        f"Bank version: `{inventory['version']}`.",
        f"Experiment: `{experiment_id or 'pending'}`; split: `{summary['split'] or 'pending'}`; status: `{summary['status']}`.",
        "",
        "Project-authored synthetic debugging fixtures; not SWE-bench or real GitHub issues.",
        "Difficulty is static metadata, not empirically established agent difficulty.",
        "",
        "## Outcomes",
        "",
        "Denominator: independently evaluated coding outcomes; infrastructure and pending outcomes are shown separately.",
        "",
        "| Condition | Evaluated | Solved | Rate | Infrastructure | Pending/unevaluated | Tokens | USD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition, result in by_condition.items():
        lines.append(
            f"| {condition} | {result['evaluated']} | {result['solved']} | {result['success_rate']} | {result['infrastructure_failures']} | {result['pending_or_unevaluated']} | {result['confirmed_tokens']} | {result['cost_usd']} |"
        )
    if not cells:
        lines.append("\nPending: no API-backed benchmark experiment has been executed.")
    lines += [
        "",
        "## Paired exploratory analysis",
        "",
        "No exploratory result promotes configurations. Repeated attempts are clustered by task.",
        "",
        "```json",
        json.dumps(comparisons, indent=2),
        "```",
        "",
        "## Held-out comparison",
        "",
        "See paired analysis above."
        if summary["split"] == "test"
        else "Pending: no held-out test comparison in this report.",
        "",
        (
            "Legacy task_003 was previously evaluated in Milestone 1; seven test fixtures are fresh. Fresh-only test comparisons are recorded separately in summary.json."
            if suite == "debug"
            else "Both RepoBench test repositories have no recorded agent exposure. Their empirical performance remains pending."
        ),
        "## Cost and uncertainty",
        "",
        "Missing USD values mean unpriced, never zero. Tokens/cost per solved task, bootstrap intervals, difficulty/category breakdowns, and history are in summary.json.",
        "Attempt-level Wilson intervals are descriptive; paired task-level bootstrap/sign tests handle repeated attempts.",
        "",
        "![Success](success.png)",
        "![Difficulty](difficulty.png)",
        "![Categories](categories.png)",
        "![Dev history](dev.png)",
        "![Decisions](acceptance.png)",
        "![Failures](failures.png)",
        "![Runtime](wall_seconds.png)",
        "![Tools](tool_calls.png)",
        "![Tokens per solved task](tokens_per_solved.png)",
        "![Cost per solved task](cost_per_solved.png)",
    ]
    lines += [
        "",
        "## Configuration versions",
        "",
        "```json",
        json.dumps(summary["config_versions"], indent=2),
        "```",
        "",
        "## Experiment API accounting",
        "",
        "Includes incomplete runs and unresolved reservations; upper bounds are not invoice totals.",
        "",
        "```json",
        json.dumps(summary["overall_api_usage"], indent=2),
        "```",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return output / "report.md"
