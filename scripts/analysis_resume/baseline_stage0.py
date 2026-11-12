"""Free baseline-repeat inventory, recorded QA verification, and CLI preflights.

Run with .venv/bin/python. This module never imports a runner, constructs an API
client, invokes Docker, runs fixture code, or invokes benchmark run/validate.
"""

import argparse
import hashlib
import inspect
import json
import os
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11"
REPORT = ROOT / "docs/baseline-repeat-2026-11-11.md"
EARLIER = ROOT / "artifacts/benchmark/repobench/real/experiments/e6ceb4bc2c4c4525ba52dbd9e2310f05"
CAPS = {"max_usd": 1.99, "max_tokens": 744000, "max_api_calls": 1240}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def input_hashes():
    paths = set()
    for directory in ("artifacts", "src", "config", "tasks", "suites", "benchmark"):
        paths.update(p for p in (ROOT / directory).rglob("*") if p.is_file() and not p.is_symlink())
    paths.update(ROOT / p for p in ("README.md", "docs/repobench.md"))
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths) if "__pycache__" not in p.parts}


def table(headers, rows):
    return (
        "\n".join(
            [
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join("---" for _ in headers) + " |",
            ]
            + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
        )
        + "\n"
    )


def verify():
    data = read(OUT / "stage0.json")
    assert data["input_fingerprints"] == input_hashes(), (
        "Stage-0 input changed; recheck before approval"
    )
    assert all(r["qa_valid"] for suite in data["inventory"].values() for r in suite["tasks"])
    assert all(x["paid_requests_made"] is False for x in data["preflights"].values())
    assert not list((OUT).glob("*experiment*.sqlite3"))
    print(
        "Stage-0 recorded inputs unchanged; existing QA matches; all captured preflights are unpaid."
    )


def main():
    # Only trusted metadata/loaders are used; fixture Python files are hashed as text.
    from reflexforge.benchmark.cli import run, selected_entries, settings_for
    from reflexforge.benchmark.manifest import digest, load_manifest, resolve_entry
    from reflexforge.benchmark.suites import dataset_root
    from reflexforge.worker.agent import effective_budget
    from reflexforge.worker.config import AgentConfig

    before = input_hashes()
    prior = read(EARLIER / "conditions.json")
    snapshot = EARLIER / "configs/static"
    config = AgentConfig.load(snapshot)
    current = AgentConfig.load(ROOT / "config")
    assert config.version == prior["config_versions"]["static"]
    assert config.model_dump(exclude={"params"}) == current.model_dump(exclude={"params"})
    assert config.params.model_dump() == prior["settings"]["run_budget"]
    env = os.environ.copy()
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "OPENAI_MODEL": prior["settings"]["worker_model"],
            "REFLEXFORGE_INPUT_PRICE": str(prior["settings"]["worker_prices"][0]),
            "REFLEXFORGE_OUTPUT_PRICE": str(prior["settings"]["worker_prices"][1]),
            "REFLEXFORGE_IMAGE": prior["image_id"],
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    os.environ.update(
        {k: env[k] for k in ("OPENAI_MODEL", "REFLEXFORGE_INPUT_PRICE", "REFLEXFORGE_OUTPUT_PRICE")}
    )
    OUT.mkdir(parents=True, exist_ok=True)
    inventory = {}
    for suite in ("repobench", "debug"):
        data_root = dataset_root(ROOT, suite)
        manifest = load_manifest(data_root, prior["bank_version"] if suite == "repobench" else None)
        tasks = []
        for entry in manifest.entries:
            if entry.split not in ("train", "dev"):
                continue
            task, directory, _ = resolve_entry(data_root, entry)
            receipt = ROOT / "artifacts/benchmark"
            if suite == "repobench":
                receipt /= "repobench"
            receipt /= f"qa/{manifest.version}/{entry.id}.json"
            qa = read(receipt) if receipt.exists() else {}
            reference = data_root / "benchmark/references" / (entry.id + ".json")
            valid = bool(
                qa.get("valid")
                and qa.get("source_hash") == entry.source_hash
                and qa.get("reference_hash") == entry.reference_hash
                and qa.get("image_id") == prior["image_id"]
                and digest(read(reference)) == entry.reference_hash
                and (suite != "repobench" or qa.get("manifest_hash") == manifest.version)
            )
            settings = settings_for(entry.split, "static", 1, **CAPS, suite=suite)
            budget = effective_budget(settings.run_budget, task.budget).model_dump()
            if suite == "repobench":
                assert budget == prior["settings"]["run_budget"], entry.id + " budget differs"
            tasks.append(
                {
                    "task_id": entry.id,
                    "split": entry.split,
                    "family": entry.family,
                    "qa_path": str(receipt.relative_to(ROOT)),
                    "qa_valid": valid,
                    "source_hash": entry.source_hash,
                    "reference_hash": entry.reference_hash,
                    "image_id": qa.get("image_id"),
                    "budget": budget,
                }
            )
        inventory[suite] = {"bank_version": manifest.version, "tasks": tasks}
    assert all(x["qa_valid"] for x in inventory["repobench"]["tasks"]), (
        "QA missing or invalid: STOP"
    )
    # Actual earlier dev exposure is read from worker metadata, not the stale manifest exposure flag.
    exposed = set()
    sql = "SELECT DISTINCT task_id FROM runs WHERE synthetic=0 AND split='dev'"
    for path in (ROOT / "artifacts/benchmark/repobench/real/experiments").rglob(
        "experiments.sqlite3"
    ):
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        exposed.update(r[0] for r in db.execute(sql))
        db.close()
    help_commands = [
        [str(ROOT / ".venv/bin/reflexforge"), "benchmark", "--help"],
        [str(ROOT / ".venv/bin/reflexforge"), "benchmark", "run", "--help"],
        [str(ROOT / ".venv/bin/reflexforge"), "benchmark", "preflight", "--help"],
    ]
    for i, command in enumerate(help_commands):
        result = subprocess.run(
            command, cwd=ROOT, env=env, text=True, capture_output=True, check=True
        )
        (OUT / f"help-{i}.txt").write_text(result.stdout)
    commands, preflights = {}, {}
    selections = [("smoke", "repobench", "train", ["task_101"], 1)]
    for suite, prefix in (("repobench", "main"), ("debug", "optional-debug")):
        for split in ("train", "dev"):
            ids = [
                t["task_id"]
                for t in inventory[suite]["tasks"]
                if t["split"] == split and t["qa_valid"]
            ]
            selections.append((prefix + "-" + split, suite, split, ids, 3))
    for label, suite, split, ids, attempts in selections:
        if not ids:
            continue
        manifest, entries = selected_entries(
            ROOT, split, ",".join(ids), inventory[suite]["bank_version"], suite
        )
        assert len(entries) == len(ids)
        command = [
            str(ROOT / ".venv/bin/reflexforge"),
            "benchmark",
            "preflight",
            "--suite",
            suite,
            "--split",
            split,
            "--tasks",
            ",".join(ids),
            "--conditions",
            "static",
            "--attempts",
            str(attempts),
            "--bank-version",
            manifest.version,
            "--max-usd",
            str(CAPS["max_usd"]),
            "--max-tokens",
            str(CAPS["max_tokens"]),
            "--max-api-calls",
            str(CAPS["max_api_calls"]),
        ]
        result = subprocess.run(
            command, cwd=ROOT, env=env, text=True, capture_output=True, check=True
        )
        commands[label] = shlex.join(command)
        preflights[label] = json.loads(result.stdout)
        assert preflights[label]["paid_requests_made"] is False
        (OUT / (label + "-preflight.txt")).write_text(result.stdout)
    after = input_hashes()
    assert before == after, "Existing input content changed: STOP"
    schema = __import__(
        "reflexforge.benchmark.settings", fromlist=["BenchmarkSettings"]
    ).BenchmarkSettings.model_json_schema()
    result = {
        "stage": 0,
        "status": "blocked_pending_execution_method_approval",
        "new_paid_commands": 0,
        "new_experiment_ids": [],
        "new_spend_usd": 0,
        "frozen_config": str(snapshot.relative_to(ROOT)),
        "frozen_config_hash": config.version,
        "current_source_config_hash": current.version,
        "behavior_matches_current_source_config": True,
        "recorded_run_settings": prior["settings"],
        "bank_version": prior["bank_version"],
        "image": prior["image_id"],
        "environment": {
            k: env[k]
            for k in (
                "PYTHONDONTWRITEBYTECODE",
                "OPENAI_MODEL",
                "REFLEXFORGE_INPUT_PRICE",
                "REFLEXFORGE_OUTPUT_PRICE",
                "REFLEXFORGE_IMAGE",
            )
        },
        "proposed_global_caps": CAPS,
        "inventory": inventory,
        "prior_dev_exposure": sorted(exposed),
        "exposure_sql": sql,
        "run_options": list(inspect.signature(run).parameters),
        "attempt_limits": schema["properties"]["attempts"],
        "conditions": schema["properties"]["conditions"],
        "preflight_commands": commands,
        "preflights": preflights,
        "blockers": [
            "CLI supports one split per command and exposes no shared-ledger option; each invocation creates its own ledger.",
            "BenchmarkRunner initializes/recovers the existing shared state and appends audit records outside the new experiment directory.",
            "Preflight has no --config option, so config/tool/budget equality is checked separately by this script.",
        ],
        "input_fingerprints": before,
    }
    (OUT / "stage0.json").write_text(json.dumps(result, indent=2) + "\n")
    write_report(result)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "stage",
                    "status",
                    "frozen_config_hash",
                    "bank_version",
                    "image",
                    "blockers",
                    "preflights",
                )
            },
            indent=2,
        )
    )


def write_report(d):
    p = [
        "# Frozen-incumbent repeated baseline — November 11, 2026",
        "",
        "Stage 0 only. No new worker experiments or paid commands have run; new experiment IDs: not available. "
        "Paid stages and outcome analysis remain pending explicit approval. Existing artifacts and source remain unchanged.",
        "",
        "Reproduce all Stage-0 numbers, queries, hashes and full preflight output:",
        "",
        "```sh",
        ".venv/bin/python scripts/analysis_resume/baseline_stage0.py",
        ".venv/bin/python scripts/analysis_resume/verify.py --baseline-stage0",
        "```",
        "",
        "## Frozen settings and QA",
        "",
        f"Frozen incumbent: `{d['frozen_config']}`; hash `{d['frozen_config_hash']}`. "
        "Its prompt, workflow, skills and tool descriptions match the current source config; "
        f"the source config hash `{d['current_source_config_hash']}` differs because its stored budgets differ. "
        "The selected frozen snapshot already has the historical RepoBench execution budgets, so it needs no edits.",
        "",
        f"Pinned bank: `{d['bank_version']}`. Pinned image: `{d['image']}`. "
        "Local Docker image availability has not been checked; no Docker operation was performed.",
        "",
        "```json",
        json.dumps(
            {
                k: d["recorded_run_settings"][k]
                for k in (
                    "worker_model",
                    "worker_temperature",
                    "worker_reasoning_effort",
                    "seed",
                    "worker_prices",
                    "run_budget",
                )
            },
            indent=2,
        ),
        "```",
        "",
        "Effective task budgets were checked against the recorded run budget for every selected RepoBench task. "
        "Existing QA receipts were checked for valid status, matching manifest/source/reference hashes and recorded image ID; "
        "actual fixture content and reference overlays were hashed without executing them. No new QA was generated.",
        "",
        table(
            ["Suite", "Split", "Task", "Family", "Existing QA matches"],
            [
                [suite, r["split"], r["task_id"], r["family"], r["qa_valid"]]
                for suite, dataset in d["inventory"].items()
                for r in dataset["tasks"]
            ],
        ),
        "",
        "Both suites consist of project-authored fixtures. Debug is optional and excluded from the proposed RepoBench schedule. "
        "Existing RepoBench dev exposure: " + ", ".join(d["prior_dev_exposure"]) + ". "
        "The manifest's previously_exposed_task_ids field below does not track later real-run exposure. "
        "Exposure SQL, executed read-only against prior real RepoBench worker databases: "
        f"`{d['exposure_sql']}`. Test task contents and outcomes are not used.",
        "",
        "## Supported options and execution blocker",
        "",
        "`benchmark run` supports `static`, `reflection`, `meta`, `candidate` conditions; "
        f"attempts range from {d['attempt_limits']['minimum']} through {d['attempt_limits']['maximum']}. "
        "Only `static` is proposed. `--split` selects exactly one of train/dev/test; test and --final are excluded. "
        "Run options from the actual CLI signature: "
        + ", ".join("`--" + x.replace("_", "-") + "`" for x in d["run_options"])
        + ". "
        "Full command help is saved alongside stage0.json.",
        "",
        *["- " + x for x in d["blockers"]],
        "",
        "Consequently, there is **no compliant unmodified benchmark CLI paid command** for this staged train+dev "
        "experiment with one shared ledger and no changes to existing artifact files. No paid command is proposed for approval yet. "
        "The existing Python API does support `BenchmarkRunner(..., shared_ledger=ledger)`. A possible resolution is an "
        "analysis-only driver using that existing API, one persistent shared ledger, and a new isolated run root populated with "
        "byte-identical frozen tasks/QA/config snapshots. It would expose the requested cap flags, implement separate approved "
        "smoke/train/dev invocations, and never change source, task content, budgets, tools or old artifacts. "
        "Implementation is pending approval of this execution-method change; paid commands would still require separate written approval.",
        "",
        "## Free preflights: exact commands and full output",
        "",
        "Recorded-price assumptions are input/output USD per million tokens, not a new price quote. "
        "Preflight bounds are reservations, not cost forecasts. Expected actual cost: not available. "
        "A proposed single shared cap is deliberately below the requested spending ceiling:",
        "",
        "```json",
        json.dumps(d["proposed_global_caps"], indent=2),
        "```",
        "",
        "Free command environment (no credentials shown):",
        "",
        "```sh",
        *["export " + k + "=" + shlex.quote(v) for k, v in d["environment"].items()],
        "```",
        "",
    ]
    main_labels = ("smoke", "main-train", "main-dev")
    total_runs = sum(d["preflights"][k]["scheduled_runs"] for k in main_labels)
    tokens = sum(d["preflights"][k]["uncapped_token_reservations"] for k in main_labels)
    calls = sum(d["preflights"][k]["max_http_calls_including_counting"] for k in main_labels)
    p += [
        f"Stage 1 schedules {d['preflights']['smoke']['scheduled_runs']} run; Stage 2 schedules "
        f"{sum(d['preflights'][k]['scheduled_runs'] for k in ('main-train', 'main-dev'))} runs. "
        f"Combined schedule: {total_runs} runs, {tokens} uncapped token reservations and {calls} HTTP calls. "
        "These are planned counts, not measurements. Independent CLI hard_usd_cap fields below do not constitute "
        "one shared cap and must not be interpreted as authorization to execute separate CLI runs.",
        "",
    ]
    for label, command in d["preflight_commands"].items():
        p += [
            f"### {label}",
            "",
            "```sh",
            command,
            "```",
            "",
            "```json",
            json.dumps(d["preflights"][label], indent=2),
            "```",
            "",
        ]
    p += [
        "The sum of conservative per-split reservation USD bounds exceeds the shared cap; "
        "the cap must remain authoritative and may prevent completion. No extrapolated spending forecast or "
        "guarantee of completing every attempt is made. Optional debug bounds are separate and are not added "
        "to the RepoBench cap or run schedule. Debug's CLI default per-run budget differs from RepoBench's; "
        "it must be treated as a separate study if selected.",
        "",
        "## Stage status and pending measurements",
        "",
        "Stage 1: awaiting compliant execution method and explicit paid approval. "
        "Stage 2: not authorized for execution. Outcomes, partial credit, consistency, Wilson intervals, "
        "task-cluster bootstrap intervals, false passes, resource stops, per-solved-task resources, "
        "new-versus-pooled rates and outcome-based resume bullets: not available until recorded runs exist. "
        "No candidate or meta-pilot is included. Dev tasks have prior exposure. "
        "Existing analysis will be extended after Stage 2; no new outcome is fabricated for this Stage-0 report.",
        "",
        "Stage-0 source: `scripts/analysis_resume/baseline_stage0.py`; raw evidence, receipt paths, input hashes "
        "and preflight captures: `scripts/analysis_resume/baseline-repeat-2026-11-11/`. "
        "Input content hashes before and after these free checks agree.",
        "",
    ]
    REPORT.write_text("\n".join(p))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify()
    else:
        main()
