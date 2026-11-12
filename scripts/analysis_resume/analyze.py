#!/usr/bin/env python3
"""Reproduce resume statistics offline using only Python's standard library.

No project modules are imported, and no task/evaluator code is executed. SQLite is
opened read-only and immutable. Held-out rows supply inventory metadata only.
All writes are confined to this directory and docs/resume-stats.md.
"""

import argparse
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
QUERIES = {
    "tables": "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
    "inventory": "SELECT run_id,task_id,split,synthetic,status,json_extract(result,'$.model') AS model FROM runs ORDER BY run_id",
    "result_non_test": "SELECT result FROM runs WHERE run_id=? AND split IN ('train','dev')",
    "experiments": "SELECT id,synthetic,settings,status FROM experiments ORDER BY id",
    "cells": "SELECT experiment_id,task_id,attempt,condition,status,result FROM benchmark_cells ORDER BY experiment_id,task_id,attempt,condition",
    "ledger": "SELECT id,experiment_id,role,model,state,calls,tokens,usd,actual_usage FROM api_usage ORDER BY id",
}
query_log = []
issues = []


def rel(p):
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def load(p):
    return json.loads(p.read_text())


def events(p):
    return [dict(json.loads(line), line=i) for i, line in enumerate(p.read_text().splitlines(), 1)]


def query(db, path, name, args=()):
    query_log.append(
        {"database": rel(path), "query": name, "sql": QUERIES[name], "parameters": args}
    )
    return [dict(r) for r in db.execute(QUERIES[name], args)]


def dec(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def fmt(x, places=6):
    if x is None:
        return "not available"
    value = dec(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else str(value)


def rate(k, n):
    if not n:
        return "not available (n=0)"
    z = NormalDist().inv_cdf(0.975)
    p = k / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{k}/{n} = {fmt(dec(k) * 100 / dec(n), 2)}% (95% Wilson {fmt(max(0, center - radius) * 100, 2)}–{fmt(min(1, center + radius) * 100, 2)}%)"


def table(headers, rows):
    def cell(x):
        return str(x).replace("|", "\\|").replace("\n", "<br>")

    return (
        "\n".join(
            [
                "| " + " | ".join(map(cell, headers)) + " |",
                "| " + " | ".join(["---"] * len(headers)) + " |",
            ]
            + ["| " + " | ".join(map(cell, row)) + " |" for row in rows]
        )
        + "\n"
    )


def summary(values, places=6):
    values = sorted(dec(v) for v in values if v is not None)
    if not values:
        return [0] + ["not available"] * 4
    n = len(values)
    median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
    return [
        n,
        fmt(sum(values) / n, places),
        fmt(median, places),
        fmt(values[0], places),
        fmt(values[-1], places),
    ]


def fingerprint():
    # Content-only guard: reading a file can change filesystem access time.
    result = {}
    for directory in (
        "artifacts",
        "src",
        "tasks",
        "suites",
        "benchmark",
        "config",
        "docs",
        "scripts",
        "tests",
    ):
        for p in sorted((ROOT / directory).rglob("*")):
            if (
                p.is_file()
                and not p.is_symlink()
                and "__pycache__" not in p.parts
                and not p.is_relative_to(Path(__file__).resolve().parent)
                and p != ROOT / "docs/resume-stats.md"
            ):
                result[rel(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    p = ROOT / "README.md"
    result[rel(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def protected(data):
    lines = [line[6:] for line in data.get("output", "").splitlines() if line.startswith("RF_QA ")]
    if not lines:
        return None
    if len(lines) != 1:
        raise ValueError("Ambiguous RF_QA records")
    q = json.loads(lines[0])
    failed = set(q["failures"]) | set(q["errors"])
    if "skipped" in q or "expected_failures" in q:
        raise ValueError("Unsupported partial-credit semantics")
    return {
        "passed": q["tests_run"] - len(failed),
        "total": q["tests_run"],
        "failed_checks": sorted(failed),
        "details": q.get("details", []),
    }


def analyze(artifact_roots=None, output_dir=None, emit_report=True):
    """Keep the original default; explicit roots allow separate new-run evidence.

    Multiple roots are read together only when explicitly selected. External
    paths stay absolute so ROOT / recorded_path continues to resolve correctly.
    --no-report preserves the earlier resume report while reconciling new runs.
    """
    global OUT
    if output_dir is not None:
        destination = Path(output_dir).resolve()
        assert destination.is_relative_to(Path(__file__).resolve().parent)
        destination.mkdir(parents=True, exist_ok=True)
        OUT = destination
    roots = sorted({Path(p).resolve() for p in (artifact_roots or [ROOT / "artifacts"])})
    assert all(p.is_dir() for p in roots), "Missing artifact root"
    query_log.clear()
    issues.clear()
    before = fingerprint()
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.is_file() and not p.is_symlink():
                before[rel(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    db_inventory, all_rows, cells, experiments, ledger = [], [], [], {}, []
    excluded = []
    for path in sorted({p for root in roots for p in root.rglob("*.sqlite3")}):
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        db.row_factory = sqlite3.Row
        tables = [r["name"] for r in query(db, path, "tables")]
        counts = {}
        for t in tables:
            sql = "SELECT COUNT(*) AS n FROM " + t
            query_log.append(
                {"database": rel(path), "query": "table_count", "sql": sql, "parameters": []}
            )
            counts[t] = db.execute(sql).fetchone()["n"]
        db_inventory.append({"path": rel(path), "tables": counts})
        if "experiments" in tables:
            for e in query(db, path, "experiments"):
                e["settings"] = json.loads(e["settings"])
                e["db"] = rel(path)
                experiments[e["id"]] = e
        if "benchmark_cells" in tables:
            for c in query(db, path, "cells"):
                c["db"] = rel(path)
                # Test cells are counted only; never parse their outcome JSON.
                e = experiments[c["experiment_id"]]
                entries = e["settings"].get("entries", [])
                test_ids = {x["id"] for x in entries if x.get("split") == "test"}
                if c["task_id"] in test_ids:
                    c["result"] = None
                else:
                    c["result"] = json.loads(c["result"]) if c["result"] else None
                cells.append(c)
        if "api_usage" in tables and "synthetic" not in path.parts:
            audit = path.parent / "audit.jsonl"
            audit_events = events(audit) if audit.exists() else []
            by_ticket = defaultdict(list)
            for ev in audit_events:
                if ev["kind"] == "api_usage":
                    by_ticket[ev["data"]["ticket"]].append(ev)
            for u in query(db, path, "ledger"):
                u["db"] = rel(path)
                es = by_ticket[u["id"]]
                u["time"] = es[0]["time"] if len(es) == 1 else None
                u["audit_line"] = es[0]["line"] if len(es) == 1 else None
                if len(es) != 1:
                    issues.append(f"Ledger ticket {u['id']} has {len(es)} matching audit events")
                elif any(
                    es[0]["data"].get(k) != u[k] for k in ("role", "model", "state", "tokens")
                ):
                    issues.append(f"Ledger/audit value mismatch: {u['id']}")
                ledger.append(u)
        if "runs" in tables:
            for row in query(db, path, "inventory"):
                row["db"] = rel(path)
                row["trace"] = rel(path.parent / "traces" / f"{row['run_id']}.jsonl")
                row["suite"] = "repobench" if "repobench" in path.parts else "debug"
                row["condition"] = "not available (standalone)"
                row["result"] = None
                if row["synthetic"] or "synthetic" in path.parts:
                    reason = (
                        "mocked optimizer demonstration"
                        if "optimization/synthetic" in rel(path)
                        else "dry-run synthetic plan"
                    )
                    excluded.append(
                        {"run_id": row["run_id"], "reason": reason, "database": rel(path)}
                    )
                    row["exclude"] = reason
                elif row["split"] != "test":
                    rr = query(db, path, "result_non_test", (row["run_id"],))
                    row["result"] = json.loads(rr[0]["result"]) if rr[0]["result"] else None
                all_rows.append(row)
        db.close()

    runs = [r for r in all_rows if not r.get("exclude")]
    duplicates = [k for k, v in Counter(r["run_id"] for r in all_rows).items() if v > 1]
    if duplicates:
        raise ValueError(f"Duplicate SQLite run IDs: {duplicates}")
    run_map = {r["run_id"]: r for r in runs}
    for r in runs:
        if "/experiments/" in r["db"]:
            eid = r["db"].split("/experiments/")[1].split("/")[0]
            r["experiment_id"] = eid
            e = experiments[eid]["settings"]
            configs = e.get("config_versions", {})
            matches = [
                c
                for c in cells
                if c["experiment_id"] == eid
                and c["result"]
                and c["result"].get("run_id") == r["run_id"]
            ]
            if len(matches) == 1:
                r["condition"] = matches[0]["condition"]
                r["attempt"] = matches[0]["attempt"]
                r["cell_status"] = matches[0]["status"]
            elif r["result"]:
                # Budget-exhausted cell has NULL result. Require unique task/config match.
                matches = [
                    c
                    for c in cells
                    if c["experiment_id"] == eid
                    and c["task_id"] == r["task_id"]
                    and configs.get(c["condition"]) == r["result"]["config_version"]
                    and c["result"] is None
                ]
                if len(matches) > 1:
                    # Repeated pending cells share a config. The controller's
                    # last running-cell event before worker start identifies
                    # the actual attempt without inferring it from row order.
                    starts = [e for e in events(ROOT / r["trace"]) if e["kind"] == "run_start"]
                    audit = Path(r["db"]).parents[3] / "audit.jsonl"
                    if not audit.is_absolute():
                        audit = ROOT / audit
                    running = [
                        e
                        for e in events(audit)
                        if e["kind"] == "benchmark_cell"
                        and e["data"].get("experiment_id") == eid
                        and e["data"].get("task_id") == r["task_id"]
                        and e["data"].get("status") == "running"
                        and e["time"] <= starts[0]["time"]
                    ]
                    if running:
                        current = max(running, key=lambda e: e["time"])["data"]
                        matches = [
                            c
                            for c in matches
                            if c["attempt"] == current["attempt"]
                            and c["condition"] == current["condition"]
                        ]
                if len(matches) == 1:
                    r["condition"] = matches[0]["condition"]
                    r["attempt"] = matches[0]["attempt"]
                    r["cell_status"] = matches[0]["status"]
                    issues.append(
                        f"Cell result missing for {r['run_id']}; condition/attempt joined from frozen task/config and controller audit where needed; worker SQLite/trace retained"
                    )
                else:
                    issues.append(f"Ambiguous condition for {r['run_id']}")

    analyzed = [r for r in runs if r["split"] in ("train", "dev")]
    for r in analyzed:
        p = ROOT / r["trace"]
        if not p.exists() or not r["result"]:
            issues.append(f"Missing trace/result: {r['run_id']}")
            continue
        es = events(p)
        r["events"] = es
        start = [e for e in es if e["kind"] == "run_start"]
        end = [e for e in es if e["kind"] == "run_end"]
        assert len(start) == len(end) == 1
        assert all(e["run_id"] == r["run_id"] for e in es)
        assert end[0]["data"] == r["result"], r["run_id"] + " SQLite/trace mismatch"
        assert start[0]["data"]["synthetic"] is False
        responses = [e for e in es if e["kind"] == "model_response"]
        assert responses and all(
            e["data"]["provider"] == "openai" and e["data"]["response_id"].startswith("resp_")
            for e in responses
        )
        r["response_models"] = sorted({e["data"]["model"] for e in responses})
        assert (
            sum(e["data"]["usage"]["input_tokens"] for e in responses)
            == r["result"]["input_tokens"]
        )
        assert (
            sum(e["data"]["usage"]["output_tokens"] for e in responses)
            == r["result"]["output_tokens"]
        )
        assert (
            sum(e["kind"] in ("tool_call", "reflection_visible_check") for e in es)
            == r["result"]["tool_calls"]
        )
        call_args = {}
        last_edit = 0
        visible = []
        reproduction = start[0]["data"]["task"]["reproduction"]
        for e in es:
            d = e["data"]
            if e["kind"] == "tool_call":
                try:
                    call_args[d["call_id"]] = json.loads(d["arguments"])
                except ValueError:
                    pass
            if e["kind"] == "tool_result":
                if d["name"] == "edit_file" and not d.get("is_error", True):
                    last_edit = e["line"]
                if d["name"] in ("run_tests", "run_shell"):
                    command = call_args.get(d["call_id"], {}).get("command")
                    if command == reproduction and "exit_code" in d["result"]:
                        visible.append(
                            {
                                "line": e["line"],
                                "exit_code": d["result"]["exit_code"],
                                "command": command,
                            }
                        )
            if e["kind"] == "reflection_visible_check":
                visible.append(
                    {"line": e["line"], "exit_code": d["exit_code"], "command": reproduction}
                )
        r["visible"] = visible[-1] if visible else None
        r["visible_fresh"] = bool(visible and visible[-1]["line"] > last_edit)
        evals = [e for e in es if e["kind"] == "evaluation"]
        assert len(evals) <= 1
        r["evaluation_line"] = evals[0]["line"] if evals else None
        r["protected"] = protected(evals[0]["data"]) if evals else None
        if evals:
            assert ("passed" if evals[0]["data"]["exit_code"] == 0 else "failed") == r["result"][
                "evaluation"
            ]
        r["api_calls"] = r["ledger_usd"] = None
        tickets = [
            u
            for u in ledger
            if u["role"] == "worker"
            and u["time"] is not None
            and start[0]["time"] <= u["time"] <= end[0]["time"]
        ]
        if tickets:
            expected_eid = (
                experiments.get(r.get("experiment_id"), {})
                .get("settings", {})
                .get("shared_budget_experiment_id", r.get("experiment_id"))
            )
            assert all(u["experiment_id"] == expected_eid for u in tickets)
            r["api_calls"] = sum(u["calls"] for u in tickets)
            r["ledger_usd"] = (
                sum((dec(u["usd"]) for u in tickets), Decimal(0))
                if all(u["usd"] is not None for u in tickets)
                else None
            )
            confirmed_tokens = sum(u["tokens"] for u in tickets if u["state"] == "finished")
            retained_tokens = sum(
                u["tokens"] for u in tickets if u["state"] in ("unknown", "reserved", "overrun")
            )
            assert confirmed_tokens == r["result"]["input_tokens"] + r["result"]["output_tokens"]
            if retained_tokens:
                assert r["result"]["usage_incomplete"]
                assert retained_tokens == r["result"]["unconfirmed_tokens"]
                r["retained_uncertain_tokens"] = retained_tokens
                issues.append(
                    f"Retained uncertain ledger reservation for {r['run_id']}; confirmed tokens reconcile; final usage unavailable"
                )
            r["ledger_tickets"] = [u["id"] for u in tickets]
            for u in tickets:
                assert not u.get("assigned_run")
                u["assigned_run"] = r["run_id"]
        errors = [e["data"] for e in es if e["kind"] == "error"]
        termination = r["result"]["termination"]
        r["resource_stop"] = (
            termination
            if termination
            in (
                "token_limit",
                "step_limit",
                "tool_call_limit",
                "wall_timeout",
                "sandbox_timeout",
                "budget_exhausted",
            )
            else None
        )
        for error in errors:
            if error.get("type") == "BudgetExceeded":
                r["resource_stop"] = "global budget: " + error["message"]
        r["tokens"] = r["result"]["input_tokens"] + r["result"]["output_tokens"]

    # Supplemental independent result is never substituted for the original outcome.
    posthoc = []
    for p in sorted({p for root in roots for p in root.rglob("recovery.json")}):
        d = load(p)
        if d.get("original_run_id") in {r["run_id"] for r in analyzed}:
            d["path"] = rel(p)
            d["checks"] = protected(d["evaluation"])
            posthoc.append(d)
    trace_files = sorted({p for root in roots for p in root.rglob("traces/*.jsonl")})
    trace_ids = {p.stem for p in trace_files}
    sqlite_ids = {r["run_id"] for r in all_rows}
    if trace_ids != sqlite_ids:
        issues.append(
            f"SQLite-only IDs: {sorted(sqlite_ids - trace_ids)}; trace-only IDs: {sorted(trace_ids - sqlite_ids)}"
        )
    qa = sorted({p for root in roots for p in root.rglob("task_*.json") if "qa" in p.parts})
    fixture_traces = sorted((ROOT / "tests/fixtures").rglob("*.jsonl"))
    synthetic_cells = [c for c in cells if experiments[c["experiment_id"]]["synthetic"]]
    unmatched = [u["id"] for u in ledger if u["role"] == "worker" and not u.get("assigned_run")]
    if unmatched:
        issues.append(f"Unmatched real worker ledger tickets: {unmatched}")
    for eid, e in experiments.items():
        if e["synthetic"] or "config_versions" not in e["settings"]:
            continue
        p = ROOT / Path(e["db"]).parent / "experiments" / eid / "conditions.json"
        assert load(p) == e["settings"]
        for c in [x for x in cells if x["experiment_id"] == eid and x["result"]]:
            rid = c["result"]["run_id"]
            if rid in run_map and run_map[rid]["split"] != "test":
                assert all(c["result"].get(k) == v for k, v in run_map[rid]["result"].items())
    after = fingerprint()
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.is_file() and not p.is_symlink():
                after[rel(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    assert before == after, "Existing input file content changed during analysis"
    evidence = {
        "artifact_roots": [str(p) for p in roots],
        "databases": db_inventory,
        "inventory": [{k: v for k, v in r.items() if k not in ("events", "result")} for r in runs],
        "runs": [{k: v for k, v in r.items() if k != "events"} for r in analyzed],
        "exclusions": excluded,
        "qa_receipt_files": list(map(rel, qa)),
        "fixture_trace_files": list(map(rel, fixture_traces)),
        "synthetic_cells": len(synthetic_cells),
        "posthoc": posthoc,
        "ledger": ledger,
        "issues": list(issues),
        "reconciliation": {
            "sqlite_runs": len(all_rows),
            "trace_files": len(trace_files),
            "trace_ids": len(trace_ids),
            "trace_only": sorted(trace_ids - sqlite_ids),
            "sqlite_only": sorted(sqlite_ids - trace_ids),
        },
        "input_fingerprints": before,
        "unchanged_inputs": len(before),
    }
    (OUT / "queries.json").write_text(json.dumps(query_log, indent=2) + "\n")
    (OUT / "evidence.json").write_text(json.dumps(evidence, indent=2, default=str) + "\n")
    if emit_report:
        report(
            runs, analyzed, excluded, qa, fixture_traces, synthetic_cells, posthoc, ledger, evidence
        )
    print(
        f"Wrote {OUT}/evidence.json; {len(runs)} real runs, {len(analyzed)} non-test runs; {len(issues)} disclosed issues"
    )
    return evidence


def report(
    runs, analyzed, excluded, qa, fixture_traces, synthetic_cells, posthoc, ledger, evidence
):
    sections = []

    def add(s):
        sections.append(s + "\n")

    comparable = [
        r
        for r in analyzed
        if r.get("visible") and r["result"]["evaluation"] in ("passed", "failed")
    ]
    false = [
        r
        for r in comparable
        if r["visible"]["exit_code"] == 0 and r["result"]["evaluation"] == "failed"
    ]
    vp = [r for r in comparable if r["visible"]["exit_code"] == 0]
    evaluated = [r for r in analyzed if r["result"]["evaluation"] in ("passed", "failed")]
    solved = [r for r in evaluated if r["result"]["evaluation"] == "passed"]
    add("# Recorded-run statistics for resume review")
    add(
        "Generated by `python3 scripts/analysis_resume/analyze.py` from this checkout. "
        "This is offline, read-only analysis: no project imports, model calls, Docker, task execution, or evaluator execution. "
        "Both debug and RepoBench are project-authored fixtures, not external benchmarks. "
        "Held-out test runs contribute inventory metadata only; their traces, outcomes, usage and timing are excluded from all analyses below."
    )
    add(
        table(
            ["Summary measure", "Verified result"],
            [
                ["Real worker runs (includes held-out existence)", len(runs)],
                [
                    "Non-test runs / distinct non-test tasks",
                    f"{len(analyzed)} / {len({(r['suite'], r['task_id']) for r in analyzed})}",
                ],
                [
                    "False passes / visible-pass runs with independent outcomes",
                    rate(len(false), len(vp)),
                ],
                ["False passes / all comparable runs", rate(len(false), len(comparable))],
                [
                    "Full-task successes / contemporaneously evaluated runs",
                    rate(len(solved), len(evaluated)),
                ],
                ["Excluded SQLite worker records", len(excluded)],
            ],
        )
    )
    add("## Reproduction and exact queries")
    add(
        "Run from the repository root:\n\n```sh\npython3 scripts/analysis_resume/analyze.py\n```\n\n"
        "The script rewrites only its generated outputs in `scripts/analysis_resume/` and `docs/resume-stats.md`. "
        "`evidence.json` contains per-run metrics, evaluator failure details, source paths, ledger ticket IDs and input SHA-256 hashes. "
        "`queries.json` lists every executed SQL query, database path and bound parameter. "
        "SQLite connections use `mode=ro&immutable=1`; this assumes no concurrent writer or pending WAL changes. "
        "The exploratory structural inspection is independently reproducible with "
        "`python3 scripts/analysis_resume/inspect_records.py > scripts/analysis_resume/inspection.txt`."
    )
    add(
        "Verify deterministic regeneration, unchanged input hashes, inventory IDs and unique ledger assignment with "
        "`python3 scripts/analysis_resume/verify.py`. Results are saved to `scripts/analysis_resume/verification.json`; "
        "the additional inventory-only verification SQL is `SELECT run_id FROM runs`."
    )
    add(
        "Named SQL templates (table-count queries are also logged):\n\n```sql\n"
        + "\n".join("-- " + k + "\n" + v + ";" for k, v in QUERIES.items())
        + "\n```"
    )
    add(
        "Trace queries are explicit Python filters in `analyze.py`: `run_start`, `run_end`, `model_response`, "
        "`tool_call` joined to `tool_result` by `call_id`, `reflection_visible_check`, `evaluation`, and `error`. "
        "Protected-check totals come only from recorded `RF_QA` JSON. API ledger rows join audit `api_usage` events by "
        "`id = ticket`, then join the uniquely enclosing worker `run_start.time <= api_usage.time <= run_end.time`, "
        "with an experiment/shared-budget ID cross-check. No API-call counts are inferred from generation counts. "
        "All displayed noninteger statistics are truncated toward zero, never rounded up; untruncated recorded values remain in `evidence.json`. "
        "All rates use descriptive 95% Wilson intervals with the standard normal quantile. Reused tasks violate independent-trial assumptions; "
        "these small, adaptively selected samples are too small to establish general performance or configuration improvement."
    )
    add("## Inventory and exclusions")
    inventory = Counter(
        (r["suite"], r["split"], r["condition"], r["model"] or "not available") for r in runs
    )
    add(
        table(
            ["Suite", "Split", "Condition", "Configured model", "Real runs"],
            [list(k) + [v] for k, v in sorted(inventory.items())],
        )
    )
    for suite in ("debug", "repobench"):
        add(
            f"{suite} split counts: "
            + "; ".join(
                f"{split} = {sum(r['suite'] == suite and r['split'] == split for r in runs)}"
                for split in ("train", "dev", "test")
            )
            + "."
        )
    add(
        "Standalone debug runs do not record a benchmark condition. They use a fixed configuration, but are labeled "
        "“not available (standalone)” rather than silently counted as explicit `static` cells. "
        "The model column records the configured alias; non-test provider response model names are "
        + ", ".join(
            "`" + m + "`"
            for m in sorted({m for r in analyzed for m in r.get("response_models", [])})
        )
        + ". "
        "Real non-test inclusion requires non-synthetic SQLite and trace flags, a non-synthetic store, and recorded OpenAI "
        "`resp_` responses with token usage. This is local provenance, not external verification of provider billing."
    )
    add(
        table(
            ["Excluded SQLite worker record reason", "Records"],
            sorted(Counter(r["reason"] for r in excluded).items()),
        )
    )
    add(
        f"Additional excluded record populations: {len(synthetic_cells)} pending synthetic benchmark cells "
        f"(plans, not worker executions); {len(qa)} fixture-QA task receipt files "
        f"(baseline/reference/mutant checks, not worker attempts); {len(fixture_traces)} mocked reflector fixture JSONL files under tests/fixtures. "
        "These populations have different units and are not added to the excluded worker count. "
        "QA versions can repeat tasks; each receipt file is counted once. Exact paths and excluded worker IDs are in `evidence.json`."
    )
    add("## False-pass analysis")
    add(
        "A visible result is the last recorded execution of the exact reproduction command from `run_start.task.reproduction`, "
        "through either `run_tests` or `run_shell`; arbitrary probes and model summaries are not treated as full visible tests. "
        "Exit zero means visible pass. The primary matrix uses the last observed result, with stale results explicitly flagged below. "
        "Independent pass/fail comes from the original evaluator event and reconciled worker outcome. "
        "Runs with no independent outcome are unevaluated, not failed. False-pass rate is reported both conditional on visible pass "
        "and over all comparable runs."
    )
    matrix_rows = []
    for suite in ("debug", "repobench"):
        for split in ("train", "dev"):
            group = [r for r in analyzed if (r["suite"], r["split"]) == (suite, split)]
            pair = [r for r in comparable if r in group]
            cats = Counter(
                ("pass" if r["visible"]["exit_code"] == 0 else "fail", r["result"]["evaluation"])
                for r in pair
            )
            visible_pass = sum(r["visible"]["exit_code"] == 0 for r in pair)
            matrix_rows.append(
                [
                    suite,
                    split,
                    len(group),
                    len(pair),
                    cats["pass", "failed"],
                    cats["pass", "passed"],
                    cats["fail", "failed"],
                    cats["fail", "passed"],
                    len(group) - len(pair),
                    rate(cats["pass", "failed"], visible_pass),
                    rate(cats["pass", "failed"], len(pair)),
                ]
            )
    add(
        table(
            [
                "Suite",
                "Split",
                "Runs",
                "Comparable n",
                "Visible pass / eval fail",
                "Both pass",
                "Both fail",
                "Visible fail / eval pass",
                "Unpaired",
                "False / visible passes",
                "False / comparable",
            ],
            matrix_rows,
        )
    )
    add(
        table(
            [
                "Run ID",
                "Task / condition",
                "Visible result (trace line)",
                "After last successful edit?",
                "Original independent result (trace line)",
                "Checks passed",
            ],
            [
                [
                    f"`{r['run_id']}`",
                    f"{r['task_id']} / {r['condition']}",
                    ("passed" if r["visible"]["exit_code"] == 0 else "failed")
                    + f" (L{r['visible']['line']})"
                    if r.get("visible")
                    else "not available",
                    "yes" if r.get("visible_fresh") else "no",
                    r["result"]["evaluation"]
                    + (f" (L{r['evaluation_line']})" if r.get("evaluation_line") else ""),
                    f"{r['protected']['passed']}/{r['protected']['total']}"
                    if r.get("protected")
                    else "not available",
                ]
                for r in analyzed
            ],
        )
    )
    stale = [r for r in analyzed if r.get("visible") and not r["visible_fresh"]]
    fresh = [r for r in comparable if r["visible_fresh"]]
    add(
        f"Stale visible observations: {len(stale)}: "
        + ", ".join("`" + r["run_id"] + "`" for r in stale)
        + ". "
        "A later edit makes that visible result insufficient evidence about the final patch. "
        "Restricting to visible tests after the final edit gives "
        + rate(len([r for r in fresh if r in false]), len(fresh))
    )
    fresh_rows = []
    for suite in ("debug", "repobench"):
        for split in ("train", "dev"):
            group = [r for r in analyzed if (r["suite"], r["split"]) == (suite, split)]
            pair = [r for r in fresh if r in group]
            cats = Counter(
                (r["visible"]["exit_code"] == 0, r["result"]["evaluation"]) for r in pair
            )
            fresh_rows.append(
                [
                    suite,
                    split,
                    len(pair),
                    cats[True, "failed"],
                    cats[True, "passed"],
                    cats[False, "failed"],
                    cats[False, "passed"],
                    len(group) - len(pair),
                    rate(cats[True, "failed"], len(pair)),
                ]
            )
    add(
        "For comparison of the submitted final patch, the strict matrix excludes stale visible results as well as unevaluated runs:"
    )
    add(
        table(
            [
                "Suite",
                "Split",
                "Fresh comparable n",
                "False passes",
                "Both pass",
                "Both fail",
                "Visible fail / eval pass",
                "Stale or unpaired",
                "False / fresh comparable",
            ],
            fresh_rows,
        )
    )
    add(
        "False-pass categories below are analyst interpretations of the recorded failed-check names and assertion details; "
        "they are not causal proof. No evaluator was rerun."
    )
    category = {
        "test_cancelled_acquisition_releases": "cancellation edge case: acquisition left a job leased rather than queued",
        "test_cancelled_processing_retries": "cancellation edge case: processing left a job leased rather than queued",
        "test_input_ownership": "nested mutable input aliasing: later list mutation changed owned configuration",
        "test_instances_do_not_share_state": "shared mutable defaults: one instance mutated state visible to another",
        "test_cleanup_failure_preserves_original": "cleanup error representation: recorded exception object instead of expected error string",
    }
    failure_rows = []
    for r in false:
        for check in r["protected"]["failed_checks"]:
            short = check.rsplit(".", 1)[-1]
            failure_rows.append(
                [
                    f"`{r['run_id']}`",
                    r["suite"] + "/" + r["split"],
                    r["task_id"],
                    check,
                    category.get(short, "See recorded assertion details in evidence.json"),
                    f"{r['trace']}:L{r['evaluation_line']}",
                ]
            )
    add(
        table(
            [
                "False-pass run",
                "Suite/split",
                "Task",
                "Failed protected check",
                "Category / evidence-based explanation",
                "Evidence",
            ],
            failure_rows,
        )
    )
    add("## Partial credit and full-task success")
    add(
        "The unit is a protected unittest check in recorded `RF_QA`: `tests_run - unique(failures ∪ errors)`. "
        "This is a diagnostic count, not an official weighted task score. No counts are reconstructed from current hidden-test source. "
        "Legacy debug evaluators only recorded an exit code or pass marker, so their check denominators are not available."
    )
    partial = Counter(
        (
            r["suite"],
            r["split"],
            r["task_id"],
            f"{r['protected']['passed']}/{r['protected']['total']}",
        )
        for r in analyzed
        if r.get("protected")
    )
    add(
        table(
            ["Suite", "Split", "Task", "Checks passed / run", "Run count"],
            [list(k) + [v] for k, v in sorted(partial.items())],
        )
    )
    rows = []
    for suite in ("debug", "repobench"):
        for split in ("train", "dev"):
            g = [r for r in analyzed if (r["suite"], r["split"]) == (suite, split)]
            ev = [r for r in g if r in evaluated]
            rows.append(
                [
                    suite,
                    split,
                    rate(sum(r in solved for r in ev), len(ev)),
                    sum(not r.get("protected") for r in g),
                    len({r["task_id"] for r in ev}),
                    len({r["task_id"] for r in ev if r in solved}),
                ]
            )
    add(
        table(
            [
                "Suite",
                "Split",
                "Full-task successes / evaluated attempts",
                "Check count unavailable",
                "Distinct evaluated tasks",
                "Tasks with any successful attempt",
            ],
            rows,
        )
    )
    add("## Cost and efficiency")
    add(
        "Tokens are recorded cumulative input plus output (cached input is included, reasoning is not added again). "
        "Tool calls and wall seconds come from reconciled worker results; wall time includes worker orchestration and original independent evaluation. "
        "API calls are ledger HTTP requests, including input-token counting, not just generations. "
        "USD comes exclusively from `api_usage.usd`, summed by matched ticket; it is the ledger upper-bound token-price estimate, "
        "not a measured invoice. The ledger does not apply the cached-input discount, whereas `RunResult.cost_usd` may do so; "
        "that separate estimator is not substituted here. Standalone debug API calls and ledger USD are not available. "
        "Missing values are excluded from summaries and their coverage is shown. Meta-agent calls are excluded from worker/task totals."
    )
    metrics = [
        ("tokens", "tokens"),
        ("api_calls", "API calls"),
        ("tool_calls", "tool calls"),
        ("wall_seconds", "wall seconds"),
        ("ledger_usd", "ledger USD upper bound"),
    ]
    for r in analyzed:
        r["tool_calls"] = r["result"]["tool_calls"]
        r["wall_seconds"] = r["result"]["wall_seconds"]
    add(
        table(
            [
                "Run ID",
                "Task / condition",
                "Tokens",
                "API calls",
                "Tool calls",
                "Wall seconds",
                "Ledger USD upper bound",
            ],
            [
                [
                    f"`{r['run_id']}`",
                    r["task_id"] + " / " + r["condition"],
                    r["tokens"],
                    fmt(r["api_calls"]),
                    r["tool_calls"],
                    fmt(r["wall_seconds"]),
                    fmt(r["ledger_usd"], 10),
                ]
                for r in analyzed
            ],
        )
    )
    cost_rows = []
    for label, g in [("all non-test", analyzed)] + [
        (s, [r for r in analyzed if r["suite"] == s]) for s in ("debug", "repobench")
    ]:
        for key, name in metrics:
            cost_rows.append(
                [label, name] + summary([r[key] for r in g], 10 if key == "ledger_usd" else 6)
            )
    add(
        table(
            ["Per-run population", "Metric", "Available n", "Mean", "Median", "Min", "Max"],
            cost_rows,
        )
    )
    task_groups = defaultdict(list)
    for r in analyzed:
        task_groups[r["suite"], r["split"], r["task_id"]].append(r)
    task_totals = []
    for (suite, split, tid), g in sorted(task_groups.items()):
        d = {"suite": suite, "split": split, "task": tid, "runs": len(g)}
        for key, _ in metrics:
            d[key] = (
                sum((dec(r[key]) for r in g), Decimal(0))
                if all(r[key] is not None for r in g)
                else None
            )
        task_totals.append(d)
    add(
        "Per-task resources sum **all recorded non-test worker attempts and conditions** for each suite/task. "
        "This is observed cumulative task expenditure, not the cost of one attempt, a matched-config comparison, "
        "or cost per solved task. Any missing run-level value makes that task metric unavailable."
    )
    add(
        table(
            [
                "Suite/split",
                "Task",
                "Runs",
                "Total tokens",
                "Total API calls",
                "Total tool calls",
                "Total wall seconds",
                "Total ledger USD upper bound",
            ],
            [
                [r["suite"] + "/" + r["split"], r["task"], r["runs"]]
                + [fmt(r[k], 10 if k == "ledger_usd" else 6) for k, _ in metrics]
                for r in task_totals
            ],
        )
    )
    add(
        table(
            ["Per-task population", "Metric", "Available tasks", "Mean", "Median", "Min", "Max"],
            [
                [label, name] + summary([r[key] for r in g], 10 if key == "ledger_usd" else 6)
                for label, g in [("all non-test", task_totals)]
                + [(s, [r for r in task_totals if r["suite"] == s]) for s in ("debug", "repobench")]
                for key, name in metrics
            ],
        )
    )
    meta = [u for u in ledger if u["role"] != "worker"]
    add(
        f"Separate recorded meta overhead: {sum(u['calls'] for u in meta)} ledger API calls; "
        f"{sum(u['tokens'] for u in meta)} tokens; ${fmt(sum((dec(u['usd']) for u in meta), Decimal(0)), 10)} ledger USD upper bound. "
        "It includes pilots that stopped before worker comparison and must not be attributed to any single worker."
    )
    add("## Variance and repeated configurations")
    repeated = defaultdict(list)
    for r in analyzed:
        if r.get("experiment_id"):
            # config_version hashes all executable worker config, including parameters.
            key = (
                r["suite"],
                r["split"],
                r["task_id"],
                r["result"]["model"],
                r["result"]["config_version"],
            )
            repeated[key].append(r)
    repeats = [(k, g) for k, g in sorted(repeated.items()) if len(g) > 1]
    if repeats:
        add(
            "Repeated configurations match suite, split, task, configured model and execution-config hash. "
            "Frozen conditions also record bank, image and sampling; these are checked below before interpreting consistency. "
            "Different candidate hashes are not pooled as repeated attempts."
        )
        for key, g in repeats:
            add(
                f"Task `{key[2]}`, execution config `{key[4]}`: "
                + ", ".join(f"`{r['run_id']}` = {r['result']['evaluation']}" for r in g)
                + ". "
                "Original independently evaluated success: "
                + rate(
                    sum(r["result"]["evaluation"] == "passed" for r in g),
                    sum(r["result"]["evaluation"] in ("passed", "failed") for r in g),
                )
                + ". "
                "An unevaluated original run cannot establish repeat-outcome consistency; see the separate recovered-patch result below."
            )
            conditions = [load(ROOT / Path(r["db"]).parents[1] / "conditions.json") for r in g]
            matches = all(
                (x["bank_version"], x["image_id"], x["sampling"])
                == (
                    conditions[0]["bank_version"],
                    conditions[0]["image_id"],
                    conditions[0]["sampling"],
                )
                for x in conditions
            )
            assert matches
            add(
                "The repeated runs have matching frozen bank version, image ID and sampling. "
                "No variance estimate is justified by the available contemporaneous outcomes."
            )
    else:
        add("No task has multiple real attempts under the same recorded execution configuration.")
    add(
        "Run counts per non-test task (including different conditions): "
        + ", ".join(f"{r['task']}={r['runs']}" for r in task_totals)
        + "."
    )
    add("## Resource stops")
    stops = [r for r in analyzed if r.get("resource_stop")]
    add(
        table(
            ["Suite", "Split", "Stop reason", "Runs", "Original independent passes / stopped runs"],
            [
                [
                    suite,
                    split,
                    reason,
                    len(g),
                    rate(sum(r["result"]["evaluation"] == "passed" for r in g), len(g)),
                ]
                for (suite, split, reason), g in group_stops(stops)
            ],
        )
    )
    add(
        "All resource stops: "
        + rate(len(stops), len(analyzed))
        + ". Original independent success among stopped runs: "
        + rate(sum(r["result"]["evaluation"] == "passed" for r in stops), len(stops))
        + "."
    )
    add(
        "Stopped run IDs: "
        + ", ".join(
            f"`{r['run_id']}` ({r['resource_stop']}; {r['result']['evaluation']})" for r in stops
        )
        + ". "
        f"Explicit step-limit stops = {sum(r.get('resource_stop') in ('step_limit', 'tool_call_limit') for r in analyzed)}; "
        f"explicit time-limit stops = {sum(r.get('resource_stop') in ('wall_timeout', 'sandbox_timeout') for r in analyzed)}. "
        "A global token-limit exception recorded historically as `controller_error` is classified from its recorded `BudgetExceeded` error, "
        "without changing the original outcome."
    )
    add("## Reconciliation, recovery and caveats")
    rc = evidence["reconciliation"]
    add(
        f"SQLite worker rows = {rc['sqlite_runs']}; worker JSONL files = {rc['trace_files']}; unique trace filename run IDs = {rc['trace_ids']}. "
        f"SQLite-only IDs = {len(rc['sqlite_only'])}; trace-only IDs = {len(rc['trace_only'])}. "
        f"The SQLite total partitions into {len(runs)} real + {len(excluded)} excluded worker records. "
        f"Real runs partition into {len(analyzed)} non-test + {len(runs) - len(analyzed)} held-out existence-only records. "
        f"For all {len(analyzed)} non-test runs, run-end JSON equals SQLite result, model-usage token sums and tool counts reconcile. "
        "Held-out traces are deliberately not opened for reconciliation beyond file existence. "
        "Benchmark cell payloads, when present, agree with worker results; frozen conditions.json agrees with SQLite experiment metadata."
    )
    add(
        table(
            ["Database", "Table row counts"],
            [
                [d["path"], ", ".join(k + "=" + str(v) for k, v in d["tables"].items())]
                for d in evidence["databases"]
            ],
        )
    )
    add(
        "Disclosed mismatches / ambiguities:\n\n" + "\n".join("- " + x for x in evidence["issues"])
        if evidence["issues"]
        else "No undisclosed reconciliation mismatches found."
    )
    for d in posthoc:
        add(
            f"Supplemental post-hoc evaluation `{d['posthoc_id']}` for original run `{d['original_run_id']}`: "
            f"{d['status']}, {d['checks']['passed']}/{d['checks']['total']} protected checks. Source: `{d['path']}`. "
            "The original evaluation remains `not_run`; this recovered patch is not another worker attempt and is excluded from primary matrices, "
            "success rates and resource summaries. " + d["limitations"]
        )
    assigned = [u for u in ledger if u.get("assigned_run")]
    add(
        f"Ledger reconciliation: {len(assigned)} worker HTTP-call rows mapped uniquely to non-test run time windows, "
        f"{sum(u['tokens'] for u in assigned)} recorded tokens, "
        f"${fmt(sum((dec(u['usd']) for u in assigned), Decimal(0)), 10)} USD upper bound. "
        f"Unmatched worker ledger rows = {sum(u['role'] == 'worker' and not u.get('assigned_run') for u in ledger)}. "
        "Per-run ledger tokens agree with worker tokens. Counting requests retain zero-token/zero-USD ledger entries. "
        f"Ledger states: {dict(Counter(u['state'] for u in ledger))}. "
        "Standalone debug runs predate shared-ledger coverage; missing ledger values remain unavailable."
    )
    add(
        f"Content hashes before and after extraction agree for {evidence['unchanged_inputs']} existing input files "
        "(artifacts, source, tasks, suites, benchmark, config, docs, scripts, tests and README; analysis outputs excluded). "
        "Patches are embedded in worker trace/cell JSON rather than universally stored as separate patch files; "
        "absence of a separate patch file is not a missing worker. The recovered patch has separate artifacts. "
        "Local artifacts are Git-ignored, so reproduction requires this recorded checkout. "
        "Small authored fixtures, prior task exposure, adaptive dev reuse, and incomplete repeated outcomes prevent broad reliability or improvement claims."
    )
    add("## Candidate resume bullets")
    add(
        "These describe instrumentation and observed failure detection, not external benchmark performance or demonstrated optimization gains."
    )
    bullets = [
        f"Built an auditable coding-agent evaluation pipeline; reconciled {len(analyzed)} recorded train/dev runs across {len({(r['suite'], r['task_id']) for r in analyzed})} project-authored debugging tasks using SQLite and JSONL evidence.",
        f"Identified {len(false)} visible-test false passes across {len({r['task_id'] for r in false})} project-authored tasks through independent protected checks, exposing cancellation, mutable-state and cleanup-reporting defects.",
        f"Instrumented worker resource accounting across {len([r for r in analyzed if r['api_calls'] is not None])} ledger-covered runs, reconciling {sum(u['calls'] for u in assigned)} API requests and {sum(u['tokens'] for u in assigned)} recorded tokens.",
        f"Separated resource exhaustion from patch correctness: {sum(r['result']['evaluation'] == 'passed' for r in stops)} token-limited runs still passed independent evaluation among {len(stops)} recorded resource stops.",
    ]
    producers = [
        "`analyze.py`: `inventory` + `result_non_test`; `runs` filtered to train/dev; distinct `(suite, task_id)`.",
        "`analyze.py`: `comparable` / `false`; last exact-reproduction tool result joined to original `evaluation`; `RF_QA.failures` and `errors`.",
        "`analyze.py`: `ledger`; audit-ticket/time-window join; `assigned` sums of `calls` and `tokens`.",
        "`analyze.py`: `resource_stop` from `run_end.termination` and `error`; original independent `evaluation == passed`.",
    ]
    for bullet, producer in zip(bullets, producers):
        add(
            "- "
            + bullet
            + "\n\n  Number source: `python3 scripts/analysis_resume/analyze.py`; "
            + producer
        )
    (ROOT / "docs/resume-stats.md").write_text("\n".join(sections))


def group_stops(stops):
    groups = defaultdict(list)
    for r in stops:
        groups[r["suite"], r["split"], r["resource_stop"]].append(r)
    return sorted(groups.items())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        action="append",
        help="Artifact directory to read; repeat for multiple roots. Default: repository artifacts only.",
    )
    parser.add_argument(
        "--output-dir", type=Path, help="New evidence directory under scripts/analysis_resume"
    )
    parser.add_argument("--no-report", action="store_true", help="Preserve docs/resume-stats.md")
    args = parser.parse_args()
    analyze(args.artifact_root, args.output_dir, not args.no_report)
