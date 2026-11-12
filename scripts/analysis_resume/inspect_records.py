"""Offline structural inspection. Never print held-out result fields."""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in sorted((ROOT / "artifacts").rglob("*.sqlite3")):
    db = sqlite3.connect(p.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print(
        "\nDB",
        p.relative_to(ROOT),
        {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables},
    )
    if "runs" in tables:
        for r in db.execute("SELECT run_id,task_id,split,synthetic,status FROM runs"):
            print(dict(r))
            if r["split"] == "test" or r["synthetic"]:
                continue
            result = json.loads(
                db.execute("SELECT result FROM runs WHERE run_id=?", (r["run_id"],)).fetchone()[0]
                or "{}"
            )
            print({k: v for k, v in result.items() if k != "patch"})
            trace = p.parent / "traces" / (r["run_id"] + ".jsonl")
            if trace.exists():
                for i, line in enumerate(trace.read_text().splitlines(), 1):
                    e = json.loads(line)
                    if e["kind"] in ("evaluation", "error", "reflection_visible_check") or (
                        e["kind"] == "tool_result"
                        and e["data"]["name"] in ("run_tests", "run_shell")
                    ):
                        print("EVENT", i, e["kind"], e["data"])
    if "experiments" in tables:
        for r in db.execute("SELECT id,synthetic,status,settings FROM experiments"):
            s = json.loads(r["settings"])
            print("EXPERIMENT", r["id"], r["synthetic"], r["status"], "SETTINGS KEYS", list(s))
    if "benchmark_cells" in tables:
        for r in db.execute(
            "SELECT experiment_id,task_id,attempt,condition,status,result FROM benchmark_cells"
        ):
            d = dict(r)
            v = json.loads(d.pop("result") or "{}")
            print("CELL", d, "run_id", v.get("run_id"))
    if "api_usage" in tables:
        print(
            "LEDGER",
            [
                dict(r)
                for r in db.execute(
                    "SELECT experiment_id,role,state,COUNT(*) AS rows,SUM(calls) AS calls,SUM(tokens) AS tokens,SUM(usd) AS usd FROM api_usage GROUP BY experiment_id,role,state"
                )
            ],
        )
    db.close()
for p in sorted((ROOT / "artifacts/benchmark/repobench/posthoc").rglob("*.json")):
    print("POSTHOC", p.relative_to(ROOT), p.read_text())
