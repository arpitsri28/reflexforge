"""Read-only accounting of the smoke CLI startup failure; no execution or retry."""

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11/isolated-cli"


def main():
    plan = json.loads((OUTPUT / "roots.json").read_text())
    for name, expected in plan["original_file_hashes"].items():
        assert hashlib.sha256((REPO / name).read_bytes()).hexdigest() == expected, name
    for row in plan["copies"]:
        for key in ("source", "copy"):
            assert hashlib.sha256(Path(row[key]).read_bytes()).hexdigest() == row["original_sha256"]
    roots = {}
    sql_log = []
    for label, root_path in plan["roots"].items():
        root = Path(root_path)
        databases = []
        usage = []
        for path in sorted(root.rglob("*.sqlite3")):
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            tables_sql = "SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"
            sql_log.append({"database": str(path), "sql": tables_sql})
            tables = list(db.execute(tables_sql))
            counts = {}
            for table in tables:
                query = 'SELECT COUNT(*) AS n FROM "' + table["name"] + '"'
                sql_log.append({"database": str(path), "sql": query})
                counts[table["name"]] = db.execute(query).fetchone()["n"]
            if "api_usage" in counts:
                query = "SELECT id,experiment_id,role,state,calls,tokens,usd,actual_usage FROM api_usage"
                sql_log.append({"database": str(path), "sql": query})
                usage.extend(dict(row) for row in db.execute(query))
            databases.append({"path": str(path), "tables": counts})
            db.close()
        traces = sorted(str(p) for p in root.rglob("traces/*.jsonl"))
        snapshots = sorted(
            str(p) for p in root.glob("artifacts/benchmark/repobench/real/experiments/*")
        )
        conditions = sorted(str(p) for p in root.rglob("conditions.json"))
        roots[label] = {
            "root": root_path,
            "databases": databases,
            "ledger_rows": len(usage),
            "recorded_api_calls": sum(row["calls"] for row in usage),
            "recorded_tokens": sum(row["tokens"] for row in usage),
            "sum_recorded_ledger_usd": str(
                sum(
                    (Decimal(str(row["usd"])) for row in usage if row["usd"] is not None),
                    Decimal(0),
                )
            ),
            "worker_traces": traces,
            "worker_trace_count": len(traces),
            "worker_rows": sum(d["tables"].get("runs", 0) for d in databases),
            "snapshot_directories": snapshots,
            "condition_files": conditions,
            "independent_evaluation": "not available: no worker run started",
        }
    result = {
        "approved_smoke_command_exit_code": 1,
        "observed_startup_error": "DockerException: Error while fetching server API version: ('Connection aborted.', PermissionError(1, 'Operation not permitted'))",
        "failure_stage": "Docker client construction, before experiment metadata insertion, API client construction, or worker execution",
        "roots": roots,
        "queries": sql_log,
        "originals_and_input_copies_unchanged": True,
        "parseable_completed_smoke_run": "not available: no run exists",
        "paid_retry_executed": False,
    }
    (OUTPUT / "smoke-startup-inspection.json").write_text(json.dumps(result, indent=2) + "\n")
    report = REPO / "docs/baseline-repeat-2026-11-11.md"
    text = report.read_text()
    text = text.replace(
        "Only the free smoke preflight has run; no new paid commands, worker outcomes or experiment IDs exist yet.",
        "The separately approved smoke command was attempted and failed during Docker startup before API or worker execution. "
        "No worker outcome exists; no paid retry or train/dev execution has occurred.",
    )
    text += "\n## Approved smoke attempt: startup failure\n\n"
    text += "The approved command exited with code 1: Docker returned `PermissionError(1, 'Operation not permitted')` "
    text += "while fetching its server API version. Source control flow places this before API-client construction and worker execution. "
    text += "No retry was made. The user must decide the next step before further execution.\n\n"
    text += "| Root | Worker rows | Worker trace files | Ledger rows | Recorded API calls | Recorded tokens | Sum recorded ledger USD |\n"
    text += "| --- | --- | --- | --- | --- | --- | --- |\n"
    for label, data in roots.items():
        text += f"| {label} | {data['worker_rows']} | {data['worker_trace_count']} | {data['ledger_rows']} | {data['recorded_api_calls']} | {data['recorded_tokens']} | {data['sum_recorded_ledger_usd']} |\n"
    text += "\nNo independent evaluation ran. Completed-run shape compatibility with analyze.py is **not available**, "
    text += "because no worker record or trace was created. A partial snapshot directory and empty controller database "
    text += "remain in the smoke root and are preserved unchanged. This directory is not counted as a worker run or completed experiment. "
    text += "Original repository files and all copied inputs still match their recorded hashes.\n\n"
    text += "Reproduce: `.venv/bin/python scripts/analysis_resume/inspect_smoke_startup.py`. "
    text += "Exact read-only SQL, table counts, partial snapshot path and observed startup error: "
    text += "`scripts/analysis_resume/baseline-repeat-2026-11-11/isolated-cli/smoke-startup-inspection.json`.\n"
    # Preserve a single deterministic inspection section on rerun.
    marker = "\n## Approved smoke attempt: startup failure\n"
    if text.count(marker) > 1:
        parts = text.split(marker)
        text = parts[0] + marker + parts[-1]
    report.write_text(text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
