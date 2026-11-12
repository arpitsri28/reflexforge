"""Read-only inspection after train was interrupted on an infrastructure failure."""

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from analyze import rate, table
from monitor_repeat import inspect

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11/isolated-cli"


def main():
    plan = json.loads((OUT / "roots.json").read_text())
    root = Path(plan["roots"]["train"])
    queries = []
    path = root / "artifacts/benchmark/repobench/real/optimization.sqlite3"
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    sql = "SELECT experiment_id,task_id,attempt,condition,status,result FROM benchmark_cells ORDER BY task_id,attempt"
    queries.append({"database": str(path), "sql": sql})
    cells = [dict(r) for r in db.execute(sql)]
    for c in cells:
        c["result"] = json.loads(c["result"]) if c["result"] else None
        if c["result"]:
            c["result"].pop("patch", None)
    db.close()
    runs = []
    for path in sorted(root.rglob("experiments.sqlite3")):
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        db.row_factory = sqlite3.Row
        sql = "SELECT run_id,task_id,split,synthetic,status,result FROM runs WHERE split IN ('train','dev') ORDER BY task_id,run_id"
        queries.append({"database": str(path), "sql": sql})
        for row in db.execute(sql):
            r = dict(row)
            r["result"] = json.loads(r["result"]) if r["result"] else None
            if r["result"]:
                r["result"].pop("patch", None)
            trace = path.parent / "traces" / (r["run_id"] + ".jsonl")
            events = [
                dict(json.loads(line), line=i)
                for i, line in enumerate(trace.read_text().splitlines(), 1)
            ]
            r["trace"] = str(trace)
            r["errors"] = [e for e in events if e["kind"] in ("api_error", "error")]
            r["model_responses"] = sum(e["kind"] == "model_response" for e in events)
            r["evaluation"] = [e for e in events if e["kind"] == "evaluation"]
            runs.append(r)
        db.close()
    for name, value in plan["original_file_hashes"].items():
        assert hashlib.sha256((REPO / name).read_bytes()).hexdigest() == value, name
    data = {
        "train_process_exit_code": 130,
        "cells": cells,
        "runs": runs,
        "queries": queries,
        "monitor": inspect(),
        "original_repository_files_unchanged": True,
        "dev_started": False,
    }
    (OUT / "train-stop-inspection.json").write_text(json.dumps(data, indent=2) + "\n")
    cases = [
        r
        for r in runs
        if r["errors"]
        or not r["model_responses"]
        or (r["result"] and r["result"]["termination"] == "interrupted")
    ]
    summary = {
        "train_process_exit_code": 130,
        "cell_status_counts": dict(Counter(c["status"] for c in cells)),
        "problem_runs": cases,
        "cumulative_usage_priced_usd": data["monitor"]["cumulative_usage_priced_usd"],
        "cumulative_ledger_with_reservations_usd": data["monitor"][
            "cumulative_ledger_with_reservations_usd"
        ],
        "stop_reasons": data["monitor"]["stop_reasons"],
        "originals_unchanged": True,
        "dev_started": False,
    }
    report = REPO / "docs/baseline-repeat-2026-11-11.md"
    text = report.read_text()
    marker = "\n## Train stage stopped after infrastructure failure"
    text = text.split(marker)[0]
    block = [
        marker,
        "",
        "The user authorized train and dev. Train started after its displayed free preflight, with the approved static "
        "condition, frozen config and unchanged per-stage caps. A recorded infrastructure failure triggered interruption "
        "of the active train process. Dev has not started; no retry occurred. Remaining main outcomes and final pooled "
        "variance analysis are pending user direction.",
        "",
        table(["Train cell status", "Count"], sorted(Counter(c["status"] for c in cells).items())),
        "",
        table(
            [
                "Problem run",
                "Task",
                "Termination",
                "Independent status",
                "Model responses",
                "Recorded error",
            ],
            [
                [
                    r["run_id"],
                    r["task_id"],
                    r["result"]["termination"] if r["result"] else "not available",
                    r["result"]["evaluation"] if r["result"] else "not available",
                    r["model_responses"],
                    json.dumps([e["data"] for e in r["errors"]]),
                ]
                for r in cases
            ],
        ),
        "",
        "Cumulative recorded usage-priced ledger USD across all roots: $"
        + data["monitor"]["cumulative_usage_priced_usd"]
        + ". Including the full uncertain reservation from the interrupted generation, the ledger USD upper bound is $"
        + data["monitor"]["cumulative_ledger_with_reservations_usd"]
        + ". The request may have been billed; its final usage is not available. "
        "This is ledger token-price accounting, not an invoice. Existing original repository files are unchanged.",
        "",
        "Read-only accounting source: `.venv/bin/python scripts/analysis_resume/inspect_train_stop.py`. "
        "Exact queries, all recorded cells/runs, error evidence and monitor accounting: "
        "`scripts/analysis_resume/baseline-repeat-2026-11-11/isolated-cli/train-stop-inspection.json`.",
        "",
    ]
    eligible = [c for c in cells if c["status"] in ("solved", "coding_failure")]
    block.extend(
        [
            "Partial train coding-eligible full-task pass rate: "
            + rate(sum(c["status"] == "solved" for c in eligible), len(eligible))
            + ". "
            "This incomplete, interrupted sample is too small and selected to support performance conclusions. "
            "Infrastructure-failure and interrupted cells are not silently counted as failed coding attempts.",
            "",
        ]
    )
    report.write_text(text.rstrip() + "\n" + "\n".join(block))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
