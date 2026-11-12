"""Prepare and verify CLI input copies; optionally run one FREE preflight.

This is not an execution driver. It never invokes benchmark run, creates model
clients, runs evaluators, creates QA receipts, or modifies an existing artifact.
All paid execution remains a separate, explicitly approved CLI command.
"""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11/isolated-cli"
PLAN = OUTPUT / "roots.json"
EARLIER = REPO / "artifacts/benchmark/repobench/real/experiments/e6ceb4bc2c4c4525ba52dbd9e2310f05"
STAGES = {
    "smoke": {
        "split": "train",
        "tasks": ["task_101"],
        "attempts": 1,
        "max_tokens": 30000,
        "max_api_calls": 50,
        "max_usd": "0.20",
    },
    "train": {
        "split": "train",
        "tasks": [f"task_{i}" for i in range(101, 107)],
        "attempts": 3,
        "max_tokens": 450000,
        "max_api_calls": 760,
        "max_usd": "1.00",
    },
    "dev": {
        "split": "dev",
        "tasks": [f"task_{i}" for i in range(107, 111)],
        "attempts": 3,
        "max_tokens": 300000,
        "max_api_calls": 500,
        "max_usd": "0.75",
    },
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def original_hashes():
    result = {}
    for directory in ("artifacts", "src", "tests", "tasks", "suites", "config", "benchmark"):
        for p in sorted((REPO / directory).rglob("*")):
            if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts:
                result[str(p.relative_to(REPO))] = sha(p)
    return result


def commands(stage, plan, operation):
    selection = STAGES[stage]
    command = [
        str(REPO / ".venv/bin/reflexforge"),
        "benchmark",
        operation,
        "--root",
        plan["roots"][stage],
        "--suite",
        "repobench",
        "--split",
        selection["split"],
        "--tasks",
        ",".join(selection["tasks"]),
        "--conditions",
        "static",
        "--attempts",
        str(selection["attempts"]),
        "--bank-version",
        plan["bank_version"],
        "--max-tokens",
        str(selection["max_tokens"]),
        "--max-api-calls",
        str(selection["max_api_calls"]),
        "--max-usd",
        selection["max_usd"],
    ]
    if operation == "run":
        command.extend(["--config", plan["frozen_config"]])
    elif operation != "preflight":
        raise ValueError("Unsupported operation")
    return command


def display_command(command, plan):
    return (
        "env "
        + " ".join(shlex.quote(k + "=" + v) for k, v in plan["environment"].items())
        + " "
        + shlex.join(command)
    )


def prepare():
    if PLAN.exists():
        raise SystemExit("A plan already exists. Use verify; preparation never overwrites roots.")
    before = original_hashes()
    prior = read(EARLIER / "conditions.json")
    frozen = EARLIER / "configs/static"
    environment = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "OPENAI_MODEL": prior["settings"]["worker_model"],
        "REFLEXFORGE_IMAGE": prior["image_id"],
        "REFLEXFORGE_INPUT_PRICE": str(prior["settings"]["worker_prices"][0]),
        "REFLEXFORGE_OUTPUT_PRICE": str(prior["settings"]["worker_prices"][1]),
    }
    base = Path(
        tempfile.mkdtemp(prefix="reflexforge-baseline-repeat-2026-11-11-", dir="/private/tmp")
    )
    assert not base.is_relative_to(REPO)
    copies, roots = [], {}
    for stage, settings in STAGES.items():
        root = base / stage
        root.mkdir()
        roots[stage] = str(root)
        sources = [REPO / "suites/repobench/benchmark/manifest.json"]
        for task in settings["tasks"]:
            task_dir = REPO / "suites/repobench/tasks" / settings["split"] / task
            sources.extend(p for p in sorted(task_dir.rglob("*")) if p.is_file())
            sources.append(
                REPO / f"artifacts/benchmark/repobench/qa/{prior['bank_version']}/{task}.json"
            )
        for source in sources:
            assert source.is_file() and not source.is_symlink(), source
            destination = root / source.relative_to(REPO)
            destination.parent.mkdir(parents=True, exist_ok=True)
            assert not destination.exists()
            shutil.copyfile(source, destination)
            original, copied = sha(source), sha(destination)
            assert original == copied, source
            copies.append(
                {
                    "stage": stage,
                    "source": str(source),
                    "copy": str(destination),
                    "original_sha256": original,
                    "copy_sha256": copied,
                    "match": True,
                }
            )
    plan = {
        "roots": roots,
        "base": str(base),
        "stages": STAGES,
        "bank_version": prior["bank_version"],
        "image_id": prior["image_id"],
        "frozen_config": str(frozen),
        "frozen_config_hash": prior["config_versions"]["static"],
        "environment": environment,
        "recorded_settings": prior["settings"],
        "copies": copies,
        "frozen_file_hashes": {str(p): sha(p) for p in sorted(frozen.rglob("*")) if p.is_file()},
        "original_file_hashes": before,
        "stage_caps_total_usd": str(sum(Decimal(x["max_usd"]) for x in STAGES.values())),
    }
    assert original_hashes() == before, "Original content changed during preparation"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, indent=2) + "\n")
    lines = [
        "# Byte-identical isolated CLI inputs",
        "",
        "Generated by `.venv/bin/python scripts/analysis_resume/prepare_isolated_cli.py prepare`. "
        "No preflight or paid command has run during preparation. Every row is independently rechecked by `verify`.",
        "",
    ]
    for stage in STAGES:
        lines.extend(
            [
                f"## {stage}",
                "",
                f"Root: `{roots[stage]}`",
                "",
                "| Original path (repository-relative) | Original SHA-256 | Copy SHA-256 | Match |",
                "| --- | --- | --- | --- |",
            ]
        )
        for c in copies:
            if c["stage"] == stage:
                lines.append(
                    f"| {Path(c['source']).relative_to(REPO)} | {c['original_sha256']} | {c['copy_sha256']} | yes |"
                )
        lines.append("")
    lines.extend(
        [
            "## Frozen config (absolute original path passed to --config)",
            "",
            "| File | SHA-256 |",
            "| --- | --- |",
        ]
    )
    lines.extend(f"| {p} | {value} |" for p, value in plan["frozen_file_hashes"].items())
    (OUTPUT / "copy-hashes.md").write_text("\n".join(lines) + "\n")
    verify(plan)
    print(
        json.dumps(
            {
                "roots": roots,
                "copied_files_per_stage": {
                    stage: sum(c["stage"] == stage for c in copies) for stage in STAGES
                },
                "all_original_and_copy_hashes_match": True,
                "stage_caps_total_usd": plan["stage_caps_total_usd"],
                "file_hash_evidence": str(OUTPUT / "copy-hashes.md"),
            },
            indent=2,
        )
    )


def verify(plan):
    from reflexforge.benchmark.cli import selected_entries, settings_for
    from reflexforge.worker.agent import effective_budget
    from reflexforge.worker.config import AgentConfig

    assert original_hashes() == plan["original_file_hashes"], "Original content changed: STOP"
    for c in plan["copies"]:
        assert sha(Path(c["source"])) == c["original_sha256"], c["source"]
        assert sha(Path(c["copy"])) == c["copy_sha256"] == c["original_sha256"], c["copy"]
    for p, value in plan["frozen_file_hashes"].items():
        assert sha(Path(p)) == value, p
    config = AgentConfig.load(Path(plan["frozen_config"]))
    assert config.version == plan["frozen_config_hash"]
    assert config.params.model_dump() == plan["recorded_settings"]["run_budget"]
    for stage, selection in STAGES.items():
        root = Path(plan["roots"][stage])
        assert root.is_relative_to(Path(plan["base"])) and not root.is_relative_to(REPO)
        assert not (root / "suites/repobench/tasks/test").exists()
        manifest, entries = selected_entries(
            root,
            selection["split"],
            ",".join(selection["tasks"]),
            plan["bank_version"],
            "repobench",
        )
        settings = settings_for(
            selection["split"],
            "static",
            selection["attempts"],
            selection["max_api_calls"],
            selection["max_tokens"],
            None,
            "repobench",
        )
        for entry in entries:
            from reflexforge.benchmark.manifest import resolve_entry

            task, _, _ = resolve_entry(root / "suites/repobench", entry)
            assert effective_budget(settings.run_budget, task.budget) == config.params
            qa = read(root / f"artifacts/benchmark/repobench/qa/{manifest.version}/{entry.id}.json")
            assert qa["valid"] and qa["manifest_hash"] == manifest.version
            assert qa["source_hash"] == entry.source_hash
            assert qa["reference_hash"] == entry.reference_hash
            assert qa["image_id"] == plan["image_id"]
    print(
        "VERIFIED: all copied/original SHA-256 pairs match; frozen config, effective budgets, bank and existing QA/image match; no test fixtures copied."
    )


def spend_guard(plan):
    recovery_file = OUTPUT / "train-recovery-plan.json"
    if recovery_file.exists():
        from monitor_repeat import inspect

        accounting = inspect()
        assert not accounting["stop_reasons"], accounting["stop_reasons"]
        return {
            "cumulative_usage_priced_ledger_usd": accounting["cumulative_usage_priced_usd"],
            "cumulative_ledger_with_reservations_usd": accounting[
                "cumulative_ledger_with_reservations_usd"
            ],
            "acknowledged_preserved_train_stop": True,
            "sql": accounting["queries"],
        }
    total = Decimal(0)
    queries = [
        "SELECT state,usd,actual_usage FROM api_usage",
        "SELECT status FROM benchmark_cells WHERE status='budget_exhausted'",
    ]
    roots = dict(plan["roots"])
    retry_file = OUTPUT / "smoke-retry-preparation.json"
    if retry_file.exists():
        roots["smoke-retry"] = read(retry_file)["retry_root"]
    for root in roots.values():
        path = Path(root) / "artifacts/benchmark/repobench/real/optimization.sqlite3"
        if not path.exists():
            continue
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            for state, usd, usage in db.execute(queries[0]):
                assert state == "finished", "Uncertain ledger usage: STOP"
                if json.loads(usage or "null") is not None:
                    assert usd is not None, "Missing usage-priced ledger USD: STOP"
                    total += Decimal(str(usd))
            assert not db.execute(queries[1]).fetchall(), "Global-budget stop: STOP and ask user"
        finally:
            db.close()
    assert total <= Decimal("1.00"), (
        "Cumulative usage-priced spend exceeds $1.00: STOP and ask user"
    )
    return {"cumulative_usage_priced_ledger_usd": str(total), "sql": queries}


def preflight(stage):
    plan = read(PLAN)
    verify(plan)
    guard = spend_guard(plan)
    path = OUTPUT / f"{stage}-preflight.json"
    assert not path.exists(), (
        "Preflight capture already exists; preserve it and ask before a new capture"
    )
    command = commands(stage, plan, "preflight")
    env = os.environ.copy()
    env.update(plan["environment"])
    print("FREE PREFLIGHT:", display_command(command, plan), flush=True)
    result = subprocess.run(command, cwd=REPO, env=env, text=True, capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert data["paid_requests_made"] is False
    assert data["tasks"] == STAGES[stage]["tasks"]
    assert data["hard_usd_cap"] == float(STAGES[stage]["max_usd"])
    captured = {
        "stage": stage,
        "root": plan["roots"][stage],
        "environment": plan["environment"],
        "copy_hashes": [c for c in plan["copies"] if c["stage"] == stage],
        "guard": guard,
        "command": display_command(command, plan),
        "stdout": result.stdout,
        "preflight": data,
        "paid_command_pending_approval": display_command(commands(stage, plan, "run"), plan),
    }
    path.write_text(json.dumps(captured, indent=2) + "\n")
    verify(plan)
    render_report(plan)
    print(result.stdout, end="")
    print("PAID COMMAND — NOT EXECUTED; separate written approval required:")
    print(captured["paid_command_pending_approval"])


def render_report(plan):
    """Document only approved setup and saved free captures; never invent results."""
    lines = [
        "# Frozen-incumbent repeated baseline — November 11, 2026",
        "",
        "Current plan: isolated CLI commands with separate smoke/train/dev roots and separately allocated caps. "
        "This supersedes the earlier single-ledger proposal. No execution driver is used. "
        "Only the free smoke preflight has run; no new paid commands, worker outcomes or experiment IDs exist yet.",
        "",
        "Reproduce verification of every original/copy hash, task-content hash, frozen config, effective budget and QA receipt:",
        "",
        "```sh",
        "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/analysis_resume/prepare_isolated_cli.py verify",
        "```",
        "",
        "The `prepare` operation created new roots and refuses to overwrite an existing plan. "
        "The `preflight --stage smoke` operation captured the actual CLI output and likewise refuses to overwrite that capture. "
        "No operation in this preparation script executes `benchmark run` or generates QA receipts.",
        "",
        "## Isolated inputs and limits",
        "",
        "| Stage | Root | Tasks | Attempts/task | Scheduled runs | Token cap | API-call cap | USD cap |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for stage, values in STAGES.items():
        lines.append(
            f"| {stage} | {plan['roots'][stage]} | {', '.join(values['tasks'])} | "
            f"{values['attempts']} | {len(values['tasks']) * values['attempts']} | "
            f"{values['max_tokens']} | {values['max_api_calls']} | {values['max_usd']} |"
        )
    lines.extend(
        [
            "",
            f"The per-root hard USD caps sum to ${plan['stage_caps_total_usd']}. "
            "They are separate ledgers, not one shared ledger. Each stage needs its own displayed preflight and written approval. "
            "Before proceeding, cumulative usage-priced ledger USD across roots must be checked; if it exceeds $1.00 "
            "or any run records a global-budget stop, stop and ask the user. Recorded USD remains a token-price upper estimate, not an invoice.",
            "",
            "[Full per-file original-versus-copy SHA-256 tables](../scripts/analysis_resume/baseline-repeat-2026-11-11/isolated-cli/copy-hashes.md) "
            "show all three roots. Each input is a physical byte-identical file, not a symlink. Only the selected non-test tasks "
            "and their existing QA receipts were copied. The original complete manifest is copied unchanged; test fixtures and outcomes are excluded.",
            "",
            "| Stage | Copied input files | SHA-256 pairs match |",
            "| --- | --- | --- |",
            *[
                f"| {stage} | {sum(c['stage'] == stage for c in plan['copies'])} | yes |"
                for stage in STAGES
            ],
            "",
            "Original repository files (including existing artifacts), the absolute frozen config, and all copied input hashes "
            "are checked before and after preflight. The manifest's byte SHA-256 is distinct from its canonical bank version.",
            "",
            "## Frozen execution settings",
            "",
            f"Absolute `--config`: `{plan['frozen_config']}`.",
            "",
            f"Execution config hash: `{plan['frozen_config_hash']}`.",
            "",
            f"Pinned bank version: `{plan['bank_version']}`.",
            "",
            f"Pinned image: `{plan['image_id']}`. Existing QA receipt source/reference/manifest hashes and image IDs match. "
            "No new receipts were generated; local Docker image availability has not yet been checked.",
            "",
            "```json",
            json.dumps(
                {
                    k: plan["recorded_settings"][k]
                    for k in (
                        "worker_model",
                        "worker_temperature",
                        "worker_reasoning_effort",
                        "worker_prices",
                        "seed",
                        "run_budget",
                    )
                },
                indent=2,
            ),
            "```",
            "",
            "Static condition only; no candidate or meta-pilot. All tasks are project-authored fixtures. "
            "The existing development tasks have prior worker exposure.",
            "",
            "## Smoke: complete free preflight and pending paid command",
            "",
        ]
    )
    for stage in STAGES:
        capture = OUTPUT / f"{stage}-preflight.json"
        if not capture.exists():
            lines.extend(
                [f"{stage}: free preflight and paid approval pending the prior stage's report.", ""]
            )
            continue
        data = read(capture)
        lines.extend(
            [
                f"Root: `{data['root']}`.",
                "",
                "Exact free command:",
                "",
                "```sh",
                data["command"],
                "```",
                "",
                "Full CLI stdout:",
                "",
                "```json",
                data["stdout"].rstrip(),
                "```",
                "",
                "The preflight command has no `--config` option; config/tool/effective-budget equality is verified separately. "
                "The manifest's `previously_exposed_task_ids` is historical authoring metadata, not an up-to-date exposure log. "
                "USD bounds above are conservative reservation bounds, not measured cost or a spending forecast.",
                "",
                "Exact paid command — NOT executed; requires separate written approval:",
                "",
                "```sh",
                data["paid_command_pending_approval"],
                "```",
                "",
                f"Recorded cumulative usage-priced ledger USD before this preflight: ${data['guard']['cumulative_usage_priced_ledger_usd']}. "
                "Read-only ledger queries:",
                "",
                "```sql",
                *[q + ";" for q in data["guard"]["sql"]],
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Pending recorded-run analysis",
            "",
            "After the approved smoke run, extend the existing analysis under scripts/ to read multiple roots, verify "
            "the SQLite/JSONL record shape and reconcile the per-root ledger before asking about train execution. "
            "Final results must label each root, sum their ledgers, keep new runs separate from earlier records, and include "
            "a clearly labeled pooled view. New outcomes, confidence intervals, variance, resource-stop statistics "
            "and outcome-based resume bullets are not available until those stages have run.",
            "",
            "Raw preparation evidence: `scripts/analysis_resume/baseline-repeat-2026-11-11/isolated-cli/roots.json`. "
            "All displayed counts, hashes, caps and captured outputs come from `prepare_isolated_cli.py` and these saved records.",
            "",
        ]
    )
    (REPO / "docs/baseline-repeat-2026-11-11.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "verify", "preflight", "report"))
    parser.add_argument("--stage", choices=tuple(STAGES))
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare()
    elif args.operation == "verify":
        verify(read(PLAN))
    elif args.operation == "report":
        verify(read(PLAN))
        render_report(read(PLAN))
    elif args.stage is None:
        parser.error("preflight requires --stage")
    else:
        preflight(args.stage)
