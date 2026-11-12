"""Preserve failed startup files; inspect roots and prepare clean input-only copies.

No Docker, model, benchmark or evaluator commands are executed by this script.
Printed CLI commands are proposals for the user's terminal, not execution.
"""

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from prepare_isolated_cli import commands, display_command

REPO = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11/isolated-cli"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    original = json.loads((OUTPUT / "roots.json").read_text())
    inspections, queries = {}, []
    for label, name in original["roots"].items():
        root = Path(name)
        counts = {}
        for path in sorted(root.rglob("*.sqlite3")):
            db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
            sql = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            queries.append({"database": str(path), "sql": sql})
            for (table,) in db.execute(sql):
                query = 'SELECT COUNT(*) FROM "' + table + '"'
                queries.append({"database": str(path), "sql": query})
                counts[table] = db.execute(query).fetchone()[0]
            db.close()
        inspections[label] = {
            "root": name,
            "table_rows": counts,
            "partial_experiment_directories": [
                str(p)
                for p in sorted(root.glob("artifacts/benchmark/repobench/real/experiments/*"))
            ],
            "worker_traces": [str(p) for p in sorted(root.rglob("traces/*.jsonl"))],
        }
    failed = Path(original["roots"]["smoke"])
    failed_hashes = {str(p): sha(p) for p in sorted(failed.rglob("*")) if p.is_file()}
    evidence_path = OUTPUT / "smoke-retry-preparation.json"
    if evidence_path.exists():
        saved = json.loads(evidence_path.read_text())
        assert saved["preserved_failed_root_hashes"] == failed_hashes
        for row in saved["retry_copy_hashes"]:
            assert sha(Path(row["source"])) == sha(Path(row["copy"])) == row["sha256"]
        print(json.dumps(saved, indent=2))
        return
    for row in original["copies"]:
        assert sha(Path(row["source"])) == sha(Path(row["copy"])) == row["original_sha256"]
    retry = Path(original["base"]) / "smoke-retry-01"
    retry.mkdir(exist_ok=False)
    copied = []
    for row in original["copies"]:
        if row["stage"] != "smoke":
            continue
        source = Path(row["copy"])
        destination = retry / source.relative_to(failed)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        assert sha(destination) == row["original_sha256"]
        copied.append(
            {"source": row["source"], "copy": str(destination), "sha256": sha(destination)}
        )
    assert not list(retry.rglob("*.sqlite3"))
    assert not list(retry.rglob("*.jsonl"))
    assert not (retry / "artifacts/benchmark/repobench/real").exists()
    assert failed_hashes == {str(p): sha(p) for p in sorted(failed.rglob("*")) if p.is_file()}
    plan = json.loads(json.dumps(original))
    plan["roots"]["smoke"] = str(retry)
    result = {
        "label": "preserved-failed-smoke-startup-7ddf8ca6f8fd4030af348263c08ee8c2",
        "failed_root_preserved_in_place": str(failed),
        "preserved_failed_root_hashes": failed_hashes,
        "original_root_inspections": inspections,
        "inspection_sql": queries,
        "retry_root": str(retry),
        "retry_copy_hashes": copied,
        "retry_root_contains_runtime_artifacts": False,
        "benchmark_command_executed": False,
        "fresh_preflight_pending": True,
        "previous_preflight_output": json.loads((OUTPUT / "smoke-preflight.json").read_text())[
            "preflight"
        ],
        "free_preflight_for_user_terminal": display_command(
            commands("smoke", plan, "preflight"), plan
        ),
        "paid_command_pending_fresh_preflight_and_written_approval": display_command(
            commands("smoke", plan, "run"), plan
        ),
    }
    evidence_path.write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# Clean smoke retry inputs",
        "",
        f"Clean retry root: `{retry}`.",
        "",
        f"Failed root preserved unchanged in place: `{failed}`.",
        "",
        f"Label: `{result['label']}`.",
        "",
        "| Original file | Original SHA-256 | Retry copy SHA-256 | Match |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {r['source']} | {r['sha256']} | {sha(Path(r['copy']))} | yes |" for r in copied
    )
    lines.extend(
        [
            "",
            "No benchmark command has run in this retry root. A fresh preflight must run and be reviewed before paid approval.",
            "",
        ]
    )
    (OUTPUT / "smoke-retry-copy-hashes.md").write_text("\n".join(lines))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
