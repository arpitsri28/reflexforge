"""Check extraction provenance, reconciliations, and deterministic regeneration offline."""

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(evidence_dir=OUT, artifact_roots=None, preserve_report=False):
    evidence_dir = evidence_dir.resolve()
    assert evidence_dir.is_relative_to(OUT)
    outputs = [evidence_dir / "evidence.json", evidence_dir / "queries.json"]
    command = [sys.executable, str(OUT / "analyze.py")]
    if preserve_report:
        command.extend(["--no-report", "--output-dir", str(evidence_dir)])
    else:
        outputs.append(ROOT / "docs/resume-stats.md")
    for root in artifact_roots or []:
        command.extend(["--artifact-root", str(root)])
    original_outputs = {str(p): digest(p) for p in outputs}
    subprocess.run(command, cwd=ROOT, check=True)
    assert original_outputs == {str(p): digest(p) for p in outputs}
    evidence = json.loads((evidence_dir / "evidence.json").read_text())
    for name, expected in evidence["input_fingerprints"].items():
        assert digest(ROOT / name) == expected, name
    inventory = evidence["inventory"]
    analyzed = evidence["runs"]
    assert all(r["split"] in ("train", "dev") for r in analyzed)
    heldout = [r for r in inventory if r["split"] == "test"]
    assert all(r.get("result") is None for r in heldout)
    assert len(inventory) + len(evidence["exclusions"]) == evidence["reconciliation"]["sqlite_runs"]
    assert len(inventory) == len(analyzed) + len(heldout)
    sqlite_ids = []
    for database in evidence["databases"]:
        if "runs" not in database["tables"]:
            continue
        connection = sqlite3.connect(
            (ROOT / database["path"]).as_uri() + "?mode=ro&immutable=1", uri=True
        )
        # Inventory IDs only; this check never queries outcomes or resource fields.
        sqlite_ids.extend(r[0] for r in connection.execute("SELECT run_id FROM runs"))
        connection.close()
    trace_ids = [
        p.stem
        for root in evidence.get("artifact_roots", [str(ROOT / "artifacts")])
        for p in Path(root).rglob("traces/*.jsonl")
    ]
    assert Counter(sqlite_ids) == Counter(trace_ids)
    assert set(sqlite_ids) == {r["run_id"] for r in inventory} | {
        r["run_id"] for r in evidence["exclusions"]
    }
    tickets = [ticket for r in analyzed for ticket in r.get("ledger_tickets", [])]
    assert len(tickets) == len(set(tickets))
    assert set(tickets) == {u["id"] for u in evidence["ledger"] if u["role"] == "worker"}
    result = {
        "identical_regeneration": True,
        "input_hashes_unchanged": True,
        "sqlite_trace_inventory_ids_reconcile": True,
        "heldout_outcomes_excluded": True,
        "worker_ledger_assignment_complete_and_unique": True,
        "outputs_sha256": {str(p.relative_to(ROOT)): digest(p) for p in outputs},
        "verification_sql": "SELECT run_id FROM runs",
    }
    (evidence_dir / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-stage0",
        action="store_true",
        help="Verify repeat-baseline Stage-0 inputs without rewriting the earlier analysis",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Verify isolated evidence without rewriting the earlier report",
    )
    parser.add_argument(
        "--artifact-root", type=Path, action="append", help="Match analyze.py root selection"
    )
    args = parser.parse_args()
    if args.baseline_stage0:
        subprocess.run(
            [sys.executable, str(OUT / "baseline_stage0.py"), "--verify-only"],
            cwd=ROOT,
            check=True,
        )
    else:
        main(args.evidence_dir or OUT, args.artifact_root, args.evidence_dir is not None)
