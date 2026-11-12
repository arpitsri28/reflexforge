"""Read-only live status for the isolated budget-sensitivity study."""

import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent / "budget-sensitivity-2026-11-11"


def inspect():
    plan = json.loads((BASE / "plan.json").read_text())
    root = Path(plan["root"])
    db_path = root / "artifacts/budget-sensitivity-ledger/optimization.sqlite3"
    rows = []
    if db_path.exists():
        db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute("SELECT * FROM api_usage ORDER BY id")]
        db.close()
    usd = sum((Decimal(str(r["usd"])) for r in rows), Decimal(0))
    known = sum((Decimal(str(r["usd"])) for r in rows if r["state"] == "finished"), Decimal(0))
    cells = {}
    controller = root / "artifacts/benchmark/repobench/real/optimization.sqlite3"
    if controller.exists():
        db = sqlite3.connect(controller.as_uri() + "?mode=ro", uri=True)
        cells = {
            r[0]: r[1]
            for r in db.execute("SELECT status,COUNT(*) FROM benchmark_cells GROUP BY status")
        }
        db.close()
    stops = []
    if any(r["state"] in ("unknown", "overrun") for r in rows):
        stops.append("uncertain usage")
    if any(
        cells.get(s)
        for s in (
            "budget_exhausted",
            "infrastructure_failure",
            "unevaluated",
            "interrupted",
            "error",
        )
    ):
        stops.append("budget/infrastructure/incomplete cell")
    total = Decimal(plan["baseline_ledger_usd_upper_bound"]) + usd
    if usd > Decimal(str(plan["caps"]["max_usd"])) or total > Decimal("1.00"):
        stops.append("spending threshold exceeded")
    return {
        "root": str(root),
        "cells": cells,
        "ledger_states": {
            s: sum(r["state"] == s for r in rows) for s in sorted({r["state"] for r in rows})
        },
        "api_calls": sum(r["calls"] for r in rows),
        "ledger_token_bound": sum(r["tokens"] for r in rows),
        "known_usage_priced_usd": str(known),
        "study_ledger_usd_upper_bound": str(usd),
        "baseline_plus_study_usd_upper_bound": str(total),
        "stop_reasons": stops,
        "queries": [
            "SELECT * FROM api_usage ORDER BY id",
            "SELECT status,COUNT(*) FROM benchmark_cells GROUP BY status",
        ],
    }


if __name__ == "__main__":
    data = inspect()
    print(json.dumps(data, indent=2))
    sys.exit(1 if data["stop_reasons"] else 0)
