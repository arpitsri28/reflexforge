"""Read-only progress/accounting across all isolated baseline roots."""

import hashlib
import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11/isolated-cli"


def inspect():
    plan = json.loads((BASE / "roots.json").read_text())
    roots = dict(plan["roots"])
    retry = json.loads((BASE / "smoke-retry-preparation.json").read_text())
    roots["smoke-retry"] = retry["retry_root"]
    recovery_file = BASE / "train-recovery-plan.json"
    recovery = json.loads(recovery_file.read_text()) if recovery_file.exists() else None
    if recovery:
        for name, value in recovery["preserved_train_file_hashes"].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == value, (
                "Acknowledged stopped train root changed"
            )
        roots.update({label: values["root"] for label, values in recovery["stages"].items()})
    total, reserved = Decimal(0), Decimal(0)
    counts = {}
    stop = []
    for label, root in sorted(roots.items()):
        path = Path(root) / "artifacts/benchmark/repobench/real/optimization.sqlite3"
        if not path.exists():
            counts[label] = {"cells": {}, "usage_priced_usd": "0", "api_calls": 0, "tokens": 0}
            continue
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute("SELECT * FROM api_usage")]
        statuses = {
            r[0]: r[1]
            for r in db.execute("SELECT status,COUNT(*) FROM benchmark_cells GROUP BY status")
        }
        actual = sum(
            (
                Decimal(str(r["usd"]))
                for r in rows
                if r["state"] == "finished" and json.loads(r["actual_usage"] or "null") is not None
            ),
            Decimal(0),
        )
        upper = sum((Decimal(str(r["usd"])) for r in rows if r["usd"] is not None), Decimal(0))
        total += actual
        reserved += upper
        counts[label] = {
            "cells": statuses,
            "usage_priced_usd": str(actual),
            "ledger_with_reservations_usd": str(upper),
            "api_calls": sum(r["calls"] for r in rows),
            "tokens": sum(r["tokens"] for r in rows),
        }
        if statuses.get("budget_exhausted"):
            stop.append(label + ": global-budget stop")
        acknowledged = recovery is not None and root == recovery["acknowledged_train_root"]
        if not acknowledged and any(
            statuses.get(s)
            for s in ("infrastructure_failure", "unevaluated", "error", "interrupted")
        ):
            stop.append(label + ": infrastructure or unevaluated cell; inspect before continuing")
        if not acknowledged and any(r["state"] in ("unknown", "overrun") for r in rows):
            stop.append(label + ": uncertain usage")
        db.close()
        for trace in Path(root).rglob("traces/*.jsonl"):
            for line in trace.read_text().splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e["kind"] == "error" and e["data"].get("type") == "BudgetExceeded":
                    stop.append(label + ": BudgetExceeded trace error")
    if total > Decimal("1.00"):
        stop.append("Cumulative usage-priced USD exceeds $1.00")
    if reserved > Decimal("1.00"):
        stop.append("Cumulative ledger including uncertain reservations exceeds $1.00")
    return {
        "roots": counts,
        "cumulative_usage_priced_usd": str(total),
        "cumulative_ledger_with_reservations_usd": str(reserved),
        "stop_reasons": sorted(set(stop)),
        "acknowledged_preserved_train_stop": recovery is not None,
        "queries": [
            "SELECT * FROM api_usage",
            "SELECT status,COUNT(*) FROM benchmark_cells GROUP BY status",
        ],
    }


if __name__ == "__main__":
    result = inspect()
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["stop_reasons"] else 0)
