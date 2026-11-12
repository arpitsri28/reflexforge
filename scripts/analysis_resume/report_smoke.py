"""Summarize the existing smoke records using the extended analysis output."""

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from analyze import fmt, rate, table

REPO = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11/isolated-cli"
EVIDENCE = BASE / "smoke-evidence"


def main():
    evidence = json.loads((EVIDENCE / "evidence.json").read_text())
    retry = json.loads((BASE / "smoke-retry-preparation.json").read_text())
    plan = json.loads((BASE / "roots.json").read_text())
    execution = json.loads((BASE / "smoke-retry-execution.json").read_text())
    assert len(evidence["runs"]) == 1 and not evidence["issues"]
    run = evidence["runs"][0]
    result = run["result"]
    assert run["task_id"] == "task_101" and run["condition"] == "static"
    assert result["config_version"] == plan["frozen_config_hash"]
    assert result["usage_incomplete"] is False
    assert run["protected"] is not None and run["evaluation_line"] is not None
    for name, expected in plan["original_file_hashes"].items():
        assert hashlib.sha256((REPO / name).read_bytes()).hexdigest() == expected, name
    for row in retry["retry_copy_hashes"]:
        assert hashlib.sha256(Path(row["source"]).read_bytes()).hexdigest() == row["sha256"]
        assert hashlib.sha256(Path(row["copy"]).read_bytes()).hexdigest() == row["sha256"]
    for name, expected in retry["preserved_failed_root_hashes"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
    roots = dict(plan["roots"])
    roots["preserved-failed-smoke"] = roots.pop("smoke")
    roots["smoke-retry"] = retry["retry_root"]
    ledgers = []
    queries = []
    global_stops = []
    for label, root in sorted(roots.items()):
        path = Path(root) / "artifacts/benchmark/repobench/real/optimization.sqlite3"
        rows, experiments, cells = [], [], []
        if path.exists():
            connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
            connection.row_factory = sqlite3.Row
            for sql in (
                "SELECT * FROM api_usage ORDER BY id",
                "SELECT * FROM experiments ORDER BY id",
                "SELECT * FROM benchmark_cells ORDER BY experiment_id,task_id,attempt,condition",
            ):
                queries.append({"database": str(path), "sql": sql})
                values = [dict(r) for r in connection.execute(sql)]
                if "api_usage" in sql:
                    rows = values
                elif "benchmark_cells" in sql:
                    cells = values
                else:
                    experiments = values
            connection.close()
        assert all(r["state"] == "finished" for r in rows)
        assert all(e["status"] == "finished" for e in experiments)
        for cell in cells:
            if cell["status"] == "budget_exhausted":
                global_stops.append(cell)
        usd = sum((Decimal(str(r["usd"])) for r in rows), Decimal(0))
        usage_usd = sum(
            (
                Decimal(str(r["usd"]))
                for r in rows
                if json.loads(r["actual_usage"] or "null") is not None
            ),
            Decimal(0),
        )
        ledgers.append(
            {
                "label": label,
                "root": root,
                "ledger_rows": len(rows),
                "api_calls": sum(r["calls"] for r in rows),
                "tokens": sum(r["tokens"] for r in rows),
                "ledger_usd": str(usd),
                "usage_priced_usd": str(usage_usd),
                "uncertain": False,
            }
        )
    assert not global_stops
    total = sum((Decimal(r["ledger_usd"]) for r in ledgers), Decimal(0))
    assert total == Decimal(run["ledger_usd"]) <= Decimal("0.20")
    assert total <= Decimal("1.00")
    trace = [json.loads(line) for line in Path(run["trace"]).read_text().splitlines()]
    response_count = sum(e["kind"] == "model_response" for e in trace)
    ledger_rows = evidence["ledger"]
    assert response_count == sum(
        json.loads(r["actual_usage"] or "null") is not None for r in ledger_rows
    )
    count_requests = sum(
        json.loads(r["actual_usage"] or "null") is None and r["tokens"] == 0 for r in ledger_rows
    )
    summary = {
        "experiment_id": run["experiment_id"],
        "run_id": run["run_id"],
        "task": run["task_id"],
        "evaluation": result["evaluation"],
        "checks_passed": run["protected"]["passed"],
        "checks_total": run["protected"]["total"],
        "failed_checks": run["protected"]["failed_checks"],
        "termination": result["termination"],
        "visible": run["visible"],
        "visible_fresh": run["visible_fresh"],
        "tokens": run["tokens"],
        "tool_calls": result["tool_calls"],
        "wall_seconds": result["wall_seconds"],
        "api_calls": run["api_calls"],
        "generation_requests": response_count,
        "count_requests": count_requests,
        "ledger_usd": run["ledger_usd"],
        "root_ledgers": ledgers,
        "cumulative_ledger_usd": str(total),
        "global_budget_stops": len(global_stops),
        "same_analyzer_parser_succeeded": True,
        "issues": evidence["issues"],
        "reconciliation": evidence["reconciliation"],
        "ledger_queries": queries,
        "originals_input_copies_and_failed_root_unchanged": True,
    }
    (EVIDENCE / "smoke-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = [
        "\n## Completed smoke retry — recorded result",
        "",
        f"Experiment `{run['experiment_id']}`; worker run `{run['run_id']}`; task `{run['task_id']}`; static only. "
        f"Root: `{retry['retry_root']}`. The original failed startup root remains preserved unchanged.",
        "",
        "The user authorized the smoke retry after the earlier diagnostic-only restriction. "
        "A fresh free preflight ran in the clean retry root before the exact capped paid command. "
        "The command ran outside the sandbox with scoped execution approval; no train/dev command ran.",
        "",
        "Fresh preflight output:",
        "",
        "```json",
        execution["fresh_preflight"]["output"].strip(),
        "```",
        "",
        "Exact paid command executed:",
        "",
        "```sh",
        execution["paid_command"],
        "```",
        "",
        table(
            ["Measure", "Recorded value"],
            [
                ["Independent evaluation", result["evaluation"]],
                [
                    "Protected checks passed",
                    f"{run['protected']['passed']}/{run['protected']['total']}",
                ],
                ["Worker termination", result["termination"]],
                ["Tokens (input + output)", run["tokens"]],
                [
                    "API calls (generation / counting)",
                    f"{run['api_calls']} ({response_count} / {count_requests})",
                ],
                ["Tool calls", result["tool_calls"]],
                ["Wall seconds", fmt(result["wall_seconds"])],
                ["Ledger USD upper-bound estimate", fmt(total, 10)],
            ],
        ),
        "",
        "Failed protected check: "
        + ", ".join("`" + c + "`" for c in run["protected"]["failed_checks"])
        + ". "
        "The recorded assertion saw one charge where two distinct account/key identities required two; "
        "this supports an identity-delimiter aliasing edge-case category. No evaluator was rerun.",
        "",
        f"The last recorded visible reproduction failed at trace line {run['visible']['line']} and predates the final successful edit. "
        "Visible status for the final patch is therefore not available. This is not a confirmed false pass. "
        f"The independent evaluation event is at trace line {run['evaluation_line']}.",
        "",
        "This was a per-worker token-limit stop, not a global-ledger budget stop. The token guard can stop before "
        "the numeric cap when the next counted context plus minimum response would not fit. "
        f"Global-budget stops = {len(global_stops)}. Cumulative usage-priced ledger USD is below the user's stop threshold.",
        "",
        "Per-root recorded ledgers (startup-only and untouched roots have no ledger entries):",
        "",
        table(
            ["Root label", "API calls", "Tokens", "Ledger USD upper bound"],
            [[r["label"], r["api_calls"], r["tokens"], fmt(r["ledger_usd"], 10)] for r in ledgers],
        ),
        "",
        "Attempt-level full-task pass rate for the smoke run: "
        + rate(int(result["evaluation"] == "passed"), 1)
        + ". "
        "This single project-authored training task is too small for conclusions or a useful task-cluster bootstrap interval. "
        "Pooled/repeated-task inference remains pending the separately approved main stages.",
        "",
        "### Record-shape compatibility and reconciliation",
        "",
        "The existing analyze.py parsing and reconciliation logic successfully read the new run after adding explicit "
        "repeatable `--artifact-root`, separate `--output-dir`, and `--no-report` options. Its original default remains "
        "repository-only. No replacement parser, worker, evaluator, source or fixture change was made.",
        "",
        f"Worker SQLite rows = {evidence['reconciliation']['sqlite_runs']}; JSONL trace files = {evidence['reconciliation']['trace_files']}; "
        f"model-usage events = {response_count}; ledger request rows = {len(ledger_rows)}. "
        "Run-end JSON equals SQLite, cell payloads equal worker results, protected evaluation status agrees, "
        "trace token/tool totals reconcile, every worker ledger ticket maps uniquely to its run, "
        "and frozen condition metadata matches SQLite. No mismatches were found. Original inputs and failed startup files remain unchanged.",
        "",
        "Saved script/query sources: `scripts/analysis_resume/analyze.py`, `report_smoke.py`, "
        "and `baseline-repeat-2026-11-11/isolated-cli/smoke-evidence/{queries,evidence,smoke-summary}.json`. "
        "Reproduce the extraction, tables, unchanged-input checks and deterministic-regeneration verification with "
        "`sh scripts/analysis_resume/reproduce_smoke.sh` (offline only; no paid or benchmark command). "
        "Train and dev are not authorized by the smoke approval and remain pending.",
        "",
    ]
    report = REPO / "docs/baseline-repeat-2026-11-11.md"
    text = report.read_text()
    marker = "\n## Completed smoke retry — recorded result"
    if marker in text:
        text = text.split(marker)[0]
    text = text.replace(
        "No worker outcome exists; no paid retry or train/dev execution has occurred.",
        "A separately approved smoke retry has now completed; its recorded outcome and reconciliation appear below. Train/dev have not run.",
    )
    report.write_text(text.rstrip() + "\n" + "\n".join(lines))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
