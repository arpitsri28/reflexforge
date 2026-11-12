"""Offline comparison of recorded budget-sensitivity and matched baseline runs."""

import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import analyze  # noqa: E402
import budget_sensitivity as study  # noqa: E402
from analyze import fmt, rate, table  # noqa: E402
from inspect_sensitivity import inspect  # noqa: E402


def main():
    plan = study.load(study.PLAN)
    study.verify_inputs(plan)
    status = inspect()
    assert not status["stop_reasons"], status["stop_reasons"]
    assert not any(status["cells"].get(s) for s in ("pending", "running")), (
        "Wait for the active split to finish"
    )
    output = study.OUTPUT / "evidence"
    evidence = analyze.analyze([Path(plan["root"]) / "artifacts"], output, False)
    assert not evidence["issues"], evidence["issues"]
    old = study.load(study.BASELINE / "repeat-evidence/evidence.json")
    population = study.load(study.BASELINE / "repeat-evidence/repeat-summary.json")[
        "run_ids_by_population"
    ]["New main (train+dev; smoke excluded)"]
    baseline = [
        r
        for r in old["runs"]
        if r["run_id"] in population and r["task_id"] in sum(plan["groups"].values(), [])
    ]
    rows = []
    comparison = []
    for split, tasks in plan["groups"].items():
        for task in tasks:
            before = sorted(
                [r for r in baseline if r["task_id"] == task], key=lambda r: r["attempt"]
            )
            after = [r for r in evidence["runs"] if r["task_id"] == task]
            assert len(before) == 3 and len(after) <= 1
            if not after:
                rows.append(
                    [
                        task,
                        split,
                        ", ".join(r["result"]["evaluation"] for r in before),
                        ", ".join(
                            f"{r['protected']['passed']}/{r['protected']['total']}" for r in before
                        ),
                        "pending separate approval",
                        "not available",
                        "not available",
                        "not available",
                    ]
                )
                continue
            r = after[0]
            events = analyze.events(Path(r["trace"]))
            worker = next(e["data"] for e in events if e["kind"] == "worker_start")
            assert worker["budget"] == plan["run_budget"]
            assert r["condition"] == "static" and r["result"]["model"] == plan["model"]
            meta = study.load(Path(r["db"]).parents[1] / "conditions.json")
            assert meta["source_versions"]["static"] == plan["source_config_hash"]
            assert (
                meta["bank_version"] == plan["bank_version"]
                and meta["image_id"] == plan["image_id"]
            )
            assert meta["shared_budget_experiment_id"] == plan["study_id"]
            assert meta["settings"]["run_budget"] == plan["run_budget"]
            for b in before:
                base_cfg = next(
                    e["data"]["config"]
                    for e in analyze.events(Path(b["trace"]))
                    if e["kind"] == "worker_start"
                )
                assert {k: v for k, v in base_cfg.items() if k != "params"} == {
                    k: v for k, v in worker["config"].items() if k != "params"
                }
            item = {
                "task": task,
                "split": split,
                "new_run_id": r["run_id"],
                "experiment_id": r["experiment_id"],
                "baseline_run_ids": [b["run_id"] for b in before],
                "baseline_evaluations": [b["result"]["evaluation"] for b in before],
                "baseline_checks": [b["protected"] for b in before],
                "new_result": r["result"],
                "new_checks": r["protected"],
                "visible": r["visible"],
                "visible_fresh": r["visible_fresh"],
                "tokens": r["tokens"],
                "api_calls": r["api_calls"],
                "ledger_usd": r["ledger_usd"],
                "failed_checks": r["protected"]["failed_checks"],
            }
            comparison.append(item)
            rows.append(
                [
                    task,
                    split,
                    ", ".join(item["baseline_evaluations"]),
                    ", ".join(
                        f"{b['protected']['passed']}/{b['protected']['total']}" for b in before
                    ),
                    r["result"]["evaluation"],
                    f"{r['protected']['passed']}/{r['protected']['total']}",
                    r["result"]["termination"],
                    r["run_id"],
                ]
            )
    completed = evidence["runs"]
    successes = sum(r["result"]["evaluation"] == "passed" for r in completed)
    visible_passes = [
        r
        for r in completed
        if r.get("visible_fresh") and r.get("visible") and r["visible"]["exit_code"] == 0
    ]
    false_passes = [r for r in visible_passes if r["result"]["evaluation"] == "failed"]
    result = {
        "kind": plan["kind"],
        "study_id": plan["study_id"],
        "status": status,
        "completed_tasks": len(comparison),
        "comparison": comparison,
        "success_rate": rate(successes, len(completed)),
        "false_pass_rate": rate(len(false_passes), len(visible_passes)),
        "reconciliation": evidence["reconciliation"],
        "issues": evidence["issues"],
    }
    (study.OUTPUT / "comparison.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    lines = [
        "# Token-budget sensitivity — November 11, 2026",
        "",
        "Recorded static-incumbent follow-up, separate from candidate evaluation and from the unchanged-budget baseline. "
        "Only the per-worker cumulative-token ceiling changes. Original source, task fixtures, evaluator, incumbent, "
        "step/time limits, tools, model, sampling, bank and image are preserved.",
        "",
        f"Study `{plan['study_id']}`; root `{plan['root']}`. "
        "One new attempt per selected task is an exploratory observation; it cannot establish that the cap caused or prevented a failure. "
        "Tasks were selected post-hoc because they had unsuccessful token-limited baseline attempts; this is not an out-of-sample score. "
        "These are project-authored fixtures, and dev tasks have prior exposure.",
        "Child experiment IDs: "
        + ", ".join("`" + eid + "`" for eid in sorted({r["experiment_id"] for r in comparison}))
        + ".",
        "",
        "```json",
        json.dumps(
            {
                "baseline_budget": plan["baseline_budget"],
                "new_budget": plan["run_budget"],
                "shared_caps": plan["caps"],
            },
            indent=2,
        ),
        "```",
        "",
        table(
            [
                "Task",
                "Split",
                "Earlier independent outcomes (24k)",
                "Earlier protected checks",
                "New independent outcome (40k)",
                "New protected checks",
                "New termination",
                "New run ID",
            ],
            rows,
        ),
        "",
        "New observed full-task success among completed study runs: "
        + result["success_rate"]
        + ". "
        "This sample is too small for broad conclusions. "
        + (
            "All planned study tasks have now run."
            if len(comparison) == sum(len(ids) for ids in plan["groups"].values())
            else "The unapproved split is pending, not a failed attempt."
        ),
        "",
        table(
            ["Measure", "Recorded value"],
            [
                ["Study ledger USD upper bound", status["study_ledger_usd_upper_bound"]],
                [
                    "Prior baseline + study ledger USD upper bound",
                    status["baseline_plus_study_usd_upper_bound"],
                ],
                ["API calls", status["api_calls"]],
                ["False passes / fresh visible passes", result["false_pass_rate"]],
                ["Ledger token count", status["ledger_token_bound"]],
                ["Worker SQLite rows", evidence["reconciliation"]["sqlite_runs"]],
                ["JSONL worker traces", evidence["reconciliation"]["trace_files"]],
                [
                    "Unmatched IDs",
                    len(evidence["reconciliation"]["sqlite_only"])
                    + len(evidence["reconciliation"]["trace_only"]),
                ],
            ],
        ),
        "",
        "USD uses recorded ledger upper-bound prices, not an invoice. The earlier interrupted baseline reservation remains included in "
        "the prior-baseline bound. No new uncertain usage or infrastructure failure was recorded.",
        "",
        table(
            [
                "Task",
                "Tokens",
                "API calls",
                "Tool calls",
                "Wall seconds",
                "Ledger USD upper bound",
                "Visible after final edit?",
                "Failed protected checks",
            ],
            [
                [
                    r["task"],
                    r["tokens"],
                    r["api_calls"],
                    r["new_result"]["tool_calls"],
                    fmt(r["new_result"]["wall_seconds"]),
                    fmt(r["ledger_usd"], 10),
                    "yes" if r["visible_fresh"] else "not available",
                    ", ".join(r["failed_checks"]) or "none",
                ]
                for r in comparison
            ],
        ),
        "",
        "All worker results reconcile with trace run_end, evaluator events and model/tool counters. Every shared-ledger ticket "
        "maps uniquely to a worker; tokens reconcile with recorded usage. Config comparison confirms that policy and tools match "
        "the matched baseline; the changed budget is recorded as an execution parameter, not a candidate.",
        "",
        "Reproduce: `.venv/bin/python scripts/analysis_resume/report_sensitivity.py`. "
        "Exact SQL and bound parameters are in `evidence/queries.json`; run metadata, trace paths, check details and ledger tickets "
        "are in `evidence/evidence.json`; matched baseline run IDs and all displayed numbers are in comparison.json.",
        "",
    ]
    (study.OUTPUT / "report.md").write_text("\n".join(lines))
    if len(comparison) == sum(len(ids) for ids in plan["groups"].values()):
        snippet = [
            "### Exploratory token-budget sensitivity",
            "",
            "A separate follow-up selected task_101, task_102, task_104 and task_108 after unsuccessful",
            "token-limited baseline attempts and reran each once. Only the worker token ceiling rose",
            "from 24,000 to 40,000. Policy, model, tools, fixtures and",
            "the other execution limits stayed fixed. This was a budget-sensitivity study, not a candidate.",
            "",
            table(
                ["Task", "Checks at 24k (three earlier attempts)", "Checks at 40k", "Termination"],
                [
                    [
                        r["task"],
                        ", ".join(f"{b['passed']}/{b['total']}" for b in r["baseline_checks"]),
                        f"{r['new_checks']['passed']}/{r['new_checks']['total']}",
                        r["new_result"]["termination"],
                    ]
                    for r in comparison
                ],
            ),
            "",
            "Full-task success: **"
            + result["success_rate"]
            + "**. No full-task improvement was observed",
            "in these selected attempts; this small follow-up cannot establish a causal token-budget effect.",
            "Task_108 reached the unchanged step limit, illustrating that other execution limits can bind.",
            "",
            f"The study recorded {status['api_calls']} API calls, {status['ledger_token_bound']:,} tokens, and a ledger USD upper",
            f"bound of **${fmt(status['study_ledger_usd_upper_bound'], 10)}**, below its shared $0.40 cap. Reproduce the comparison with",
            "",
            "```bash",
            ".venv/bin/python scripts/analysis_resume/report_sensitivity.py",
            "```",
            "",
        ]
        (study.OUTPUT / "readme-summary.md").write_text("\n".join(snippet))
    verify = [
        sys.executable,
        str(Path(__file__).resolve().parent / "verify.py"),
        "--evidence-dir",
        str(output),
        "--artifact-root",
        str(Path(plan["root"]) / "artifacts"),
    ]
    subprocess.run(verify, cwd=study.REPO, check=True)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
