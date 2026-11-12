"""Prepare approved recovery input copies and FREE preflights; no paid execution."""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11/isolated-cli"
REPO = Path(__file__).resolve().parents[2]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(stage):
    plan = json.loads((BASE / "roots.json").read_text())
    file = BASE / "train-recovery-plan.json"
    if not file.exists():
        train = Path(plan["roots"]["train"])
        db = sqlite3.connect(
            (train / "artifacts/benchmark/repobench/real/optimization.sqlite3").as_uri()
            + "?mode=ro&immutable=1",
            uri=True,
        )
        old_usd = Decimal(str(db.execute("SELECT SUM(usd) FROM api_usage").fetchone()[0]))
        old_tokens, old_calls = db.execute(
            "SELECT SUM(tokens),SUM(calls) FROM api_usage"
        ).fetchone()
        db.close()
        stages = {
            "train-recovery-105": {
                "task": "task_105",
                "attempts": 1,
                "max_tokens": 30000,
                "max_api_calls": 50,
                "max_usd": "0.15",
                "logical_attempts": [2],
            },
            "train-recovery-106": {
                "task": "task_106",
                "attempts": 3,
                "max_tokens": 90000,
                "max_api_calls": 150,
                "max_usd": "0.55",
                "logical_attempts": [0, 1, 2],
            },
        }
        assert old_usd + sum(Decimal(s["max_usd"]) for s in stages.values()) <= Decimal("1.00")
        assert old_tokens + sum(s["max_tokens"] for s in stages.values()) <= 450000
        assert old_calls + sum(s["max_api_calls"] for s in stages.values()) <= 760
        hashes = {str(p): sha(p) for p in sorted(train.rglob("*")) if p.is_file()}
        copies = []
        for label, s in stages.items():
            root = Path(plan["base"]) / label
            root.mkdir(exist_ok=False)
            s["root"] = str(root)
            for c in plan["copies"]:
                if c["stage"] != "train":
                    continue
                source = Path(c["copy"])
                if (
                    source.name != "manifest.json"
                    and s["task"] not in source.parts
                    and source.name != s["task"] + ".json"
                ):
                    continue
                dest = root / source.relative_to(train)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                assert sha(source) == sha(dest) == c["original_sha256"]
                copies.append(
                    {
                        "stage": label,
                        "original": c["source"],
                        "copy": str(dest),
                        "original_sha256": c["original_sha256"],
                        "copy_sha256": sha(dest),
                    }
                )
        record = {
            "stages": stages,
            "preserved_train_file_hashes": hashes,
            "acknowledged_train_root": str(train),
            "retained_original_train_usd_upper_bound": str(old_usd),
            "retained_original_train_token_bound": old_tokens,
            "retained_original_train_api_calls": old_calls,
            "copies": copies,
            "reason": "User approved fresh-root replacement of task_105 API failure and task_106 interrupted/pending cells; retain original unknown reservation unchanged.",
        }
        file.write_text(json.dumps(record, indent=2) + "\n")
        lines = [
            "# Recovery original/copy SHA-256 comparisons",
            "",
            "| Stage | Original | Original SHA-256 | Copy SHA-256 |",
            "| --- | --- | --- | --- |",
        ]
        lines.extend(
            f"| {c['stage']} | {c['original']} | {c['original_sha256']} | {c['copy_sha256']} |"
            for c in copies
        )
        (BASE / "train-recovery-copy-hashes.md").write_text("\n".join(lines) + "\n")
    record = json.loads(file.read_text())
    for name, value in record["preserved_train_file_hashes"].items():
        assert sha(Path(name)) == value, "Preserved train artifact changed"
    for c in record["copies"]:
        assert sha(Path(c["original"])) == sha(Path(c["copy"])) == c["original_sha256"]
    if stage is None:
        print(json.dumps(record, indent=2))
        return
    s = record["stages"][stage]
    from prepare_isolated_cli import display_command

    env = os.environ.copy()
    env.update(plan["environment"])
    common = [
        "--root",
        s["root"],
        "--suite",
        "repobench",
        "--split",
        "train",
        "--tasks",
        s["task"],
        "--conditions",
        "static",
        "--attempts",
        str(s["attempts"]),
        "--bank-version",
        plan["bank_version"],
        "--max-tokens",
        str(s["max_tokens"]),
        "--max-api-calls",
        str(s["max_api_calls"]),
        "--max-usd",
        s["max_usd"],
    ]
    command = [str(REPO / ".venv/bin/reflexforge"), "benchmark", "preflight"] + common
    assert not (Path(s["root"]) / "artifacts/benchmark/repobench/real").exists(), (
        "Recovery root is not clean"
    )
    target = BASE / (stage + "-preflight.json")
    assert not target.exists(), "Preserve existing preflight"
    print(
        "All original/copy hashes match; original stopped train root remains unchanged.", flush=True
    )
    print(display_command(command, plan), flush=True)
    r = subprocess.run(command, cwd=REPO, env=env, text=True, capture_output=True, check=True)
    paid = (
        [str(REPO / ".venv/bin/reflexforge"), "benchmark", "run"]
        + common
        + ["--config", plan["frozen_config"]]
    )
    capture = {
        "stage": stage,
        "root": s["root"],
        "command": display_command(command, plan),
        "stdout": r.stdout,
        "paid_command_pending_approval": display_command(paid, plan),
        "preflight": json.loads(r.stdout),
    }
    target.write_text(json.dumps(capture, indent=2) + "\n")
    print(r.stdout, end="")
    print("Exact approved recovery command (not executed by this script):")
    print(shlex.join(paid))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", choices=("train-recovery-105", "train-recovery-106"))
    main(p.parse_args().stage)
