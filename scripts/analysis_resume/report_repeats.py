"""Offline repeated-incumbent analysis; all outcome numbers derive from saved runs.

Run after completed CLI stages: .venv/bin/python scripts/analysis_resume/report_repeats.py
It reuses analyze.py's original SQL/trace parser, preserves the original report,
and writes only analysis outputs plus docs/baseline-repeat-2026-11-11.md.
"""

import hashlib
import json
import math
import random
import subprocess
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

sys.dont_write_bytecode = True

import analyze  # noqa: E402
from analyze import fmt, rate, summary, table  # noqa: E402
from monitor_repeat import inspect  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent / "baseline-repeat-2026-11-11/isolated-cli"
NEW_OUT = BASE / "repeat-evidence"
OLD_OUT = BASE / "earlier-evidence"
SEED = 2026
RESAMPLES = 20000


def task_groups(runs):
    groups = defaultdict(list)
    for run in runs:
        groups[run["suite"], run["split"], run["task_id"]].append(run)
    return dict(sorted(groups.items()))


def numerator_denominator(run, kind):
    result = run["result"]
    if kind == "success":
        return (
            (int(result["evaluation"] == "passed"), 1)
            if result["evaluation"] in ("passed", "failed")
            else (0, 0)
        )
    visible = run.get("visible")
    eligible = bool(
        visible and run.get("visible_fresh") and result["evaluation"] in ("passed", "failed")
    )
    if not eligible:
        return (0, 0)
    failed = int(visible["exit_code"] == 0 and result["evaluation"] == "failed")
    return failed, (int(visible["exit_code"] == 0) if kind == "false_given_visible_pass" else 1)


def bootstrap(runs, kind):
    """Percentile bootstrap of task clusters, ratio of pooled eligible counts.

    Tasks with zero eligible denominator are excluded from that estimand and
    reported as unavailable, rather than silently counted as failed trials.
    All attempts of a sampled task are resampled together, including when an
    earlier task has a different number of observations in the pooled view.
    """
    clusters = []
    for group in task_groups(runs).values():
        pairs = [numerator_denominator(r, kind) for r in group]
        k, n = sum(x[0] for x in pairs), sum(x[1] for x in pairs)
        if n:
            clusters.append((k, n))
    if len(clusters) < 2:
        return {
            "tasks": len(clusters),
            "interval": "not available (fewer than two eligible task clusters)",
        }
    rng = random.Random(SEED)
    values = []
    for _ in range(RESAMPLES):
        sample = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        values.append(Decimal(sum(x[0] for x in sample)) / sum(x[1] for x in sample))
    values.sort()
    lo = values[max(0, math.ceil(Decimal(".025") * RESAMPLES) - 1)]
    hi = values[max(0, math.ceil(Decimal(".975") * RESAMPLES) - 1)]
    return {
        "tasks": len(clusters),
        "resamples": RESAMPLES,
        "seed": SEED,
        "lower": str(lo),
        "upper": str(hi),
        "interval": f"{fmt(lo * 100, 2)}–{fmt(hi * 100, 2)}%",
    }


def rate_record(runs, kind):
    pairs = [numerator_denominator(r, kind) for r in runs]
    k, n = sum(x[0] for x in pairs), sum(x[1] for x in pairs)
    return {
        "numerator": k,
        "denominator": n,
        "wilson": rate(k, n),
        "bootstrap": bootstrap(runs, kind),
    }


def resources(runs):
    names = ("tokens", "tool_calls", "wall_seconds", "ledger_usd", "api_calls")
    values = {}
    for name in names:
        entries = [
            r["result"][name] if name in ("tool_calls", "wall_seconds") else r.get(name)
            for r in runs
        ]
        values[name] = (
            None
            if any(x is None for x in entries)
            else sum((Decimal(str(x)) for x in entries), Decimal(0))
        )
    return values


def trace_errors(run):
    return [e["data"] for e in analyze.events(REPO / run["trace"]) if e["kind"] == "error"]


def failure_category(check):
    text = check.lower()
    if "delimiter" in text or "alias" in text:
        return "identity encoding / delimiter collision edge case"
    if "cancel" in text:
        return "cancellation cleanup / ownership edge case"
    if "processing_error_releases" in text:
        return "processing-error cleanup: job marked done instead of being queued for retry"
    if "input_ownership" in text or "share_state" in text:
        return "mutable configuration ownership / shared state"
    if "cleanup_failure" in text:
        return "cleanup error reporting / original-error preservation"
    if "type_validation" in text:
        return "input-type edge case: protected invalid-row validation counts were not satisfied"
    if "live_views" in text:
        return "rollback ownership: previously obtained live view retained mutated values"
    if "outer_rollback" in text:
        return "nested transaction edge case: outer rollback failed to restore inner commits"
    return "not classified; inspect recorded assertion details (no inferred root cause)"


def collect():
    plan = json.loads((BASE / "roots.json").read_text())
    retry = json.loads((BASE / "smoke-retry-preparation.json").read_text())
    root_map = {
        "preserved-failed-smoke": plan["roots"]["smoke"],
        "smoke": retry["retry_root"],
        "train": plan["roots"]["train"],
        "dev": plan["roots"]["dev"],
    }
    recovery = json.loads((BASE / "train-recovery-plan.json").read_text())
    root_map.update({label: values["root"] for label, values in recovery["stages"].items()})
    progress = inspect()
    assert not progress["stop_reasons"], progress["stop_reasons"]
    for label in ("dev", *recovery["stages"]):
        statuses = progress["roots"][label]["cells"]
        assert not any(statuses.get(s) for s in ("pending", "running")), label + " still running"
    old = analyze.analyze([REPO / "artifacts"], OLD_OUT, False)
    new = analyze.analyze([Path(root) / "artifacts" for root in root_map.values()], NEW_OUT, False)
    known_issue_ids = {"5f767ae17a5f4b04a83dd44412e9db85"}
    assert all(any(rid in issue for rid in known_issue_ids) for issue in new["issues"]), new[
        "issues"
    ]
    for run in new["runs"]:
        labels = [
            label for label, path in root_map.items() if Path(run["db"]).is_relative_to(Path(path))
        ]
        assert len(labels) == 1
        run["root_label"] = labels[0]
        assert run["condition"] == "static" and run["suite"] == "repobench"
        assert run["result"]["config_version"] == plan["frozen_config_hash"]
        assert run["result"]["model"] == plan["recorded_settings"]["worker_model"]
        assert run["result"]["usage_incomplete"] is False or run["run_id"] in known_issue_ids
        assert not any(e.get("type") == "BudgetExceeded" for e in trace_errors(run))
    eligible_status = {"solved", "coding_failure"}
    main = [
        r
        for r in new["runs"]
        if (r["root_label"] in ("train", "dev") or r["root_label"] in recovery["stages"])
        and r.get("cell_status") in eligible_status
    ]
    excluded_started = [
        r
        for r in new["runs"]
        if r["root_label"] == "train" and r.get("cell_status") not in eligible_status
    ]
    assert {r["run_id"] for r in excluded_started} == {
        "ff422b8278b34d3488970bb9494c4f42",
        "5f767ae17a5f4b04a83dd44412e9db85",
    }
    for r in main:
        r["recorded_attempt"] = r["attempt"]
        if r["root_label"] in recovery["stages"]:
            r["attempt"] = recovery["stages"][r["root_label"]]["logical_attempts"][
                r["recorded_attempt"]
            ]
    smoke = [r for r in new["runs"] if r["root_label"] == "smoke"]
    expected = {
        r["task_id"]: s
        for s in ("train", "dev")
        for r in [{"task_id": t} for t in plan["stages"][s]["tasks"]]
    }
    assert set(r["task_id"] for r in main) == set(expected)
    for (_, split, tid), group in task_groups(main).items():
        assert split == expected[tid] and len(group) == plan["stages"][split]["attempts"]
        assert {r["attempt"] for r in group} == set(range(plan["stages"][split]["attempts"]))
    assert all(r["result"]["evaluation"] in ("passed", "failed") for r in main)
    earlier = [
        r
        for r in old["runs"]
        if r["suite"] == "repobench"
        and r["condition"] == "static"
        and r["result"]["config_version"] == plan["frozen_config_hash"]
        and r["result"]["model"] == plan["recorded_settings"]["worker_model"]
    ]
    for run in earlier + new["runs"]:
        directory = Path(run["db"]).parents[1]
        metadata = json.loads((REPO / directory / "conditions.json").read_text())
        assert metadata["bank_version"] == plan["bank_version"]
        assert metadata["image_id"] == plan["image_id"]
        assert metadata["sampling"] == {
            "temperature": plan["recorded_settings"]["worker_temperature"],
            "reasoning_effort": plan["recorded_settings"]["worker_reasoning_effort"],
            "model": plan["recorded_settings"]["worker_model"],
        }
    for name, expected_hash in plan["original_file_hashes"].items():
        assert hashlib.sha256((REPO / name).read_bytes()).hexdigest() == expected_hash, name
    for row in plan["copies"]:
        assert hashlib.sha256(Path(row["copy"]).read_bytes()).hexdigest() == row["original_sha256"]
    for row in retry["retry_copy_hashes"]:
        assert hashlib.sha256(Path(row["copy"]).read_bytes()).hexdigest() == row["sha256"]
    for name, expected_hash in retry["preserved_failed_root_hashes"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected_hash, name
    return plan, root_map, old, new, main, smoke, earlier, progress


def write_report(data):
    plan, root_map, old, new, main, smoke, earlier, progress = data
    population = {
        "New main (train+dev; smoke excluded)": main,
        "New train": [r for r in main if r["split"] == "train"],
        "New dev": [r for r in main if r["split"] == "dev"],
        "New smoke (diagnostic)": smoke,
        "All new (main+smoke)": main + smoke,
        "Earlier matched incumbent only": earlier,
        "POOLED earlier matched incumbent + all new": earlier + main + smoke,
    }
    rate_data = {
        label: {
            kind: rate_record(runs, kind)
            for kind in ("success", "false_given_visible_pass", "false_over_comparable")
        }
        for label, runs in population.items()
    }
    by_task = task_groups(main)
    consistent = [
        key for key, g in by_task.items() if len({r["result"]["evaluation"] for r in g}) == 1
    ]
    inconsistent = [key for key in by_task if key not in consistent]
    false = [r for r in main + smoke if numerator_denominator(r, "false_given_visible_pass")[0]]
    totals = resources(main)
    ledger_by_root = []
    for label, root in root_map.items():
        ledger = [r for r in new["ledger"] if Path(r["db"]).is_relative_to(Path(root))]
        ledger_by_root.append(
            {
                "label": label,
                "root": root,
                "experiment_ids": sorted(
                    {r["experiment_id"] for r in new["runs"] if r["root_label"] == label}
                ),
                "ledger_rows": len(ledger),
                "api_calls": sum(r["calls"] for r in ledger),
                "tokens": sum(r["tokens"] for r in ledger),
                "confirmed_tokens": sum(r["tokens"] for r in ledger if r["state"] == "finished"),
                "retained_token_reservations": sum(
                    r["tokens"] for r in ledger if r["state"] != "finished"
                ),
                "usd": str(sum((Decimal(str(r["usd"])) for r in ledger), Decimal(0))),
            }
        )
    result = {
        "rate_populations": rate_data,
        "consistent_tasks": [k[2] for k in consistent],
        "inconsistent_tasks": [k[2] for k in inconsistent],
        "partial_check_variation_tasks": [
            key[2] for key, g in by_task.items() if len({r["protected"]["passed"] for r in g}) > 1
        ],
        "main_run_count": len(main),
        "main_task_count": len(by_task),
        "main_resource_totals": totals,
        "root_ledgers": ledger_by_root,
        "new_false_pass_run_ids": [r["run_id"] for r in false],
        "run_ids_by_population": {
            label: [r["run_id"] for r in runs] for label, runs in population.items()
        },
        "bootstrap_settings": {
            "seed": SEED,
            "resamples": RESAMPLES,
            "percentile": "nearest-rank 2.5th and 97.5th",
            "unit": "task clusters; all attempts retained",
        },
        "monitor": progress,
        "excluded_technical_runs": [r["run_id"] for r in new["runs"] if r not in main + smoke],
    }
    # The report body is built only from the recorded populations above.
    lines = [
        "# Repeated frozen-incumbent baseline — November 11, 2026",
        "",
        "Completed isolated CLI smoke, train and dev stages. Static incumbent only; no candidate, meta-pilot, "
        "new task, protected-check change or test-split evaluation. These are project-authored RepoBench fixtures, "
        "not an external benchmark. All existing dev tasks have prior worker exposure.",
        "",
        "Reproduce all numbers, SQL/trace reconciliation, deterministic bootstrap and verification:",
        "",
        "```sh",
        ".venv/bin/python scripts/analysis_resume/report_repeats.py",
        "```",
        "",
        "Raw SQL and bound parameters are saved under `isolated-cli/{repeat-evidence,earlier-evidence}/queries.json`; "
        "per-run outcomes, check details, resource values and ledger tickets are in the companion evidence.json files. "
        "Summary populations and bootstrap settings are saved in repeat-summary.json. "
        "No new execution or evaluator invocation occurs during analysis.",
        "",
        "## Summary",
        "",
        table(
            ["Measure", "Recorded value"],
            [
                ["Main runs / distinct tasks", f"{len(main)} / {len(by_task)}"],
                [
                    "Consistent / inconsistent task outcomes",
                    f"{len(consistent)} / {len(inconsistent)}",
                ],
                [
                    "Main full-task pass rate",
                    rate_data["New main (train+dev; smoke excluded)"]["success"]["wilson"],
                ],
                [
                    "Main full-task task-cluster interval",
                    rate_data["New main (train+dev; smoke excluded)"]["success"]["bootstrap"][
                        "interval"
                    ],
                ],
                [
                    "Main false passes / fresh visible-pass outcomes",
                    rate_data["New main (train+dev; smoke excluded)"]["false_given_visible_pass"][
                        "wilson"
                    ],
                ],
                [
                    "Main false-pass task-cluster interval",
                    rate_data["New main (train+dev; smoke excluded)"]["false_given_visible_pass"][
                        "bootstrap"
                    ]["interval"],
                ],
                [
                    "Tasks with varying protected-check counts",
                    len(result["partial_check_variation_tasks"]),
                ],
                [
                    "All-new ledger USD upper bound",
                    fmt(sum(Decimal(r["usd"]) for r in ledger_by_root), 10),
                ],
            ],
        ),
        "",
        "## Roots, frozen provenance, exact commands and full preflights",
        "",
        table(
            [
                "Root label",
                "Path",
                "Experiment IDs",
                "Ledger entries / API calls",
                "Ledger tokens including reservation",
                "USD upper bound",
            ],
            [
                [
                    r["label"],
                    r["root"],
                    ", ".join(r["experiment_ids"]) or "none (no worker experiment)",
                    f"{r['ledger_rows']} / {r['api_calls']}",
                    r["tokens"],
                    fmt(r["usd"], 10),
                ]
                for r in ledger_by_root
            ],
        ),
        "",
        f"Frozen config: `{plan['frozen_config']}`; execution hash `{plan['frozen_config_hash']}`. "
        f"Bank `{plan['bank_version']}`; image `{plan['image_id']}`. "
        "Existing QA matches selected source/reference/manifest hashes and image. Input copies and originals match; "
        "the failed smoke startup is preserved and is not a worker attempt.",
        "",
        "[Original/copy SHA-256 comparisons](../scripts/analysis_resume/baseline-repeat-2026-11-11/isolated-cli/copy-hashes.md); "
        "[clean smoke retry hashes](../scripts/analysis_resume/baseline-repeat-2026-11-11/isolated-cli/smoke-retry-copy-hashes.md).",
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
                    "run_budget",
                )
            },
            indent=2,
        ),
        "```",
        "",
    ]
    # More report sections are emitted below.
    build_sections(
        lines,
        result,
        population,
        rate_data,
        by_task,
        main,
        smoke,
        earlier,
        false,
        new,
        old,
        root_map,
    )
    NEW_OUT.mkdir(parents=True, exist_ok=True)
    (NEW_OUT / "repeat-summary.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (REPO / "docs/baseline-repeat-2026-11-11.md").write_text("\n".join(lines))
    return result


def build_sections(
    lines, result, population, rate_data, by_task, main, smoke, earlier, false, new, old, root_map
):
    execution = json.loads((BASE / "smoke-retry-execution.json").read_text())
    lines.extend(
        [
            "### Smoke retry",
            "",
            "```sh",
            execution["paid_command"],
            "```",
            "",
            "```json",
            execution["fresh_preflight"]["output"].strip(),
            "```",
            "",
        ]
    )
    for stage in ("train", "train-recovery-105", "train-recovery-106", "dev"):
        capture = json.loads((BASE / f"{stage}-preflight.json").read_text())
        lines.extend(
            [
                f"### {stage}",
                "",
                "Exact free command:",
                "",
                "```sh",
                capture["command"],
                "```",
                "",
                "Full preflight stdout:",
                "",
                "```json",
                capture["stdout"].strip(),
                "```",
                "",
                "Exact subsequently executed paid command:",
                "",
                "```sh",
                capture["paid_command_pending_approval"],
                "```",
                "",
            ]
        )
    recovery = json.loads((BASE / "train-recovery-plan.json").read_text())
    recovery_cap = sum(Decimal(s["max_usd"]) for s in recovery["stages"].values())
    recovery_tokens = sum(s["max_tokens"] for s in recovery["stages"].values())
    recovery_calls = sum(s["max_api_calls"] for s in recovery["stages"].values())
    excluded = [r for r in new["runs"] if r["run_id"] in result["excluded_technical_runs"]]
    lines.extend(
        [
            "### Preserved interruption and approved recovery",
            "",
            "The original train command stopped after an APIConnectionError during token counting on task_105. "
            "Interrupting its next task_106 attempt left a generation reservation uncertain. The user explicitly approved "
            "fresh-root replacement of those cells and the two pending task_106 cells. No original record was edited, "
            "recovered into a fabricated outcome, or resumed. The API-failed evaluator observation is excluded from the primary "
            "coding-success denominator because execution ended for infrastructure reasons.",
            "",
            table(
                [
                    "Excluded technical run",
                    "Task",
                    "Termination",
                    "Original independent status",
                    "Confirmed tokens",
                    "Unconfirmed token reservation",
                    "Ledger USD upper bound",
                ],
                [
                    [
                        r["run_id"],
                        r["task_id"],
                        r["result"]["termination"],
                        r["result"]["evaluation"],
                        r["tokens"],
                        r["result"]["unconfirmed_tokens"],
                        fmt(r["ledger_usd"], 10),
                    ]
                    for r in excluded
                ],
            ),
            "",
            f"The frozen original train ledger upper bound is ${fmt(recovery['retained_original_train_usd_upper_bound'], 10)}. "
            f"Recovery caps sum to ${fmt(recovery_cap, 10)}, so retained spend plus maximum recovery allocations is "
            f"${fmt(Decimal(recovery['retained_original_train_usd_upper_bound']) + recovery_cap, 10)}, below the original train cap. "
            f"Original token reservations plus recovery caps total {recovery['retained_original_train_token_bound'] + recovery_tokens}; "
            f"original HTTP calls plus recovery caps total {recovery['retained_original_train_api_calls'] + recovery_calls}. "
            "The interrupted request may have been billed; final usage/invoice cost is not available. Its full bound is included in every total ledger USD figure.",
            "",
            "[Recovery input SHA-256 comparisons](../scripts/analysis_resume/baseline-repeat-2026-11-11/isolated-cli/train-recovery-copy-hashes.md).",
            "",
        ]
    )
    lines.extend(
        [
            "The user authorized train and dev execution after the smoke report. Commands ran separately, "
            "each after its own preflight. The per-root caps remained unchanged. Preflight bounds are conservative "
            "reservations, not actual cost forecasts; no bound is substituted for recorded usage. "
            "Ledger reservations are replaced by usage-priced values after each completed call, rather than reserving "
            "all scheduled runs upfront. Counting requests have JSON-null actual_usage and zero token/USD values.",
            "",
            "## Per-task repeated outcomes and consistency",
            "",
            "Primary inference uses the completed coding-eligible train/dev observations, including approved recoveries. "
            "The API-failed and interrupted original train records are excluded from outcome denominators; "
            "their measured usage and retained reservation remain in full-study ledger accounting. "
            "The separately approved smoke diagnostic is shown separately and is included only in explicitly labeled all-new/pooled views. "
            "Full-task consistency means all recorded independent pass/fail outcomes agree; partial-check consistency is reported independently.",
            "",
        ]
    )
    attempt_rows = []
    spread_rows = []
    for (_, split, tid), group in by_task.items():
        checks = [r["protected"]["passed"] for r in group if r.get("protected")]
        spread_rows.append(
            [
                split,
                tid,
                len(group),
                "consistent"
                if len({r["result"]["evaluation"] for r in group}) == 1
                else "INCONSISTENT",
                min(checks) if checks else "not available",
                max(checks) if checks else "not available",
                max(checks) - min(checks) if checks else "not available",
            ]
        )
        for r in sorted(group, key=lambda r: r["attempt"]):
            attempt_rows.append(
                [
                    split,
                    tid,
                    r["attempt"],
                    r.get("recorded_attempt", r["attempt"]),
                    r["root_label"],
                    r["result"]["evaluation"],
                    f"{r['protected']['passed']}/{r['protected']['total']}"
                    if r.get("protected")
                    else "not available",
                    r["run_id"],
                    r["result"]["termination"],
                ]
            )
    lines.extend(
        [
            table(
                [
                    "Split",
                    "Task",
                    "Intended attempt index",
                    "Raw recorded index",
                    "Root label",
                    "Independent result",
                    "Checks passed",
                    "Run ID",
                    "Termination",
                ],
                attempt_rows,
            ),
            "",
            "Attempt indices identify intended observations. Recovery task_105 raw attempt 0 replaces original API-failed attempt 2; "
            "task_106 recovery indices replace interrupted/pending cells. Original indices are retained in raw evidence. "
            "Checks are diagnostic counts from the original RF_QA evaluator event, "
            "not weighted scores or newly executed checks.",
            "",
            table(
                [
                    "Split",
                    "Task",
                    "Attempts",
                    "Outcome consistency",
                    "Min checks passed",
                    "Max checks passed",
                    "Check-count spread",
                ],
                spread_rows,
            ),
            "",
            f"Consistent tasks = {len(result['consistent_tasks'])}; inconsistent tasks = {len(result['inconsistent_tasks'])}. "
            "Consistent: "
            + ", ".join(result["consistent_tasks"])
            + ". Inconsistent: "
            + (", ".join(result["inconsistent_tasks"]) or "none")
            + ".",
            "",
            "## Full-task pass rate and false-pass rates",
            "",
            "Independent pass/fail comes from original fresh evaluator results. A visible result is an exact reproduction "
            "command joined by tool call ID; primary false-pass analysis requires that test to occur after the final successful edit. "
            "A false pass means that visible test passed and independent evaluation failed. Stale or missing visible results "
            "are unavailable for final-patch comparison. No model summary or post-hoc recovery replaces a recorded outcome.",
            "",
        ]
    )
    metric_labels = {
        "success": "Full-task pass / independent outcomes",
        "false_given_visible_pass": "False / fresh visible-pass outcomes",
        "false_over_comparable": "False / all fresh comparable outcomes",
    }
    rate_rows = []
    for label, stats in rate_data.items():
        for kind, stat in stats.items():
            rate_rows.append(
                [
                    label,
                    metric_labels[kind],
                    stat["wilson"],
                    stat["bootstrap"]["tasks"],
                    stat["bootstrap"]["interval"],
                ]
            )
    lines.extend(
        [
            table(
                [
                    "Population",
                    "Rate and denominator",
                    "Attempt-level rate + Wilson 95% CI",
                    "Eligible task clusters",
                    "Task-cluster bootstrap 95% CI",
                ],
                rate_rows,
            ),
            "",
            f"Task-cluster bootstrap: {RESAMPLES} resamples, seed {SEED}, percentile interval using nearest-rank endpoints. "
            "Each resample draws tasks with replacement and retains all attempts within a task. The estimator is the ratio "
            "of summed eligible numerators to summed eligible denominators. Tasks without eligible denominators are excluded "
            "from that conditional estimand and shown in the availability table below. Fewer than two eligible task clusters "
            "gives not available. Any collapsed interval is descriptive and does not establish certainty.",
            "",
            "Prefer the task-cluster interval for uncertainty across these task fixtures; Wilson treats attempts as independent "
            "and can overstate precision. Even the clustered interval has few task clusters, does not capture uncertainty about "
            "unseen repositories, and is too small to establish general performance. Both intervals are descriptive, not evidence "
            "of candidate improvement or an out-of-sample benchmark score.",
            "",
        ]
    )
    availability = []
    for label, runs in population.items():
        eligible = [r for r in runs if numerator_denominator(r, "false_over_comparable")[1]]
        availability.append(
            [
                label,
                len(runs),
                sum(r["result"]["evaluation"] in ("passed", "failed") for r in runs),
                len(eligible),
                sum(r.get("visible") is not None and not r.get("visible_fresh") for r in runs),
                sum(r["result"]["evaluation"] not in ("passed", "failed") for r in runs),
            ]
        )
    lines.extend(
        [
            table(
                [
                    "Population",
                    "Runs",
                    "Independent outcomes",
                    "Fresh visible/evaluator pairs",
                    "Stale visible results",
                    "Unevaluated",
                ],
                availability,
            ),
            "",
            "The pooled view includes only earlier RepoBench static runs with matching execution config, configured model, "
            "bank, image and sampling. Earlier candidate runs, debug runs, synthetic/QA records and held-out test outcomes "
            "are excluded. The legacy unevaluated run remains unevaluated; its recovered-patch pass is not substituted. "
            "Pooling increases observation counts but does not create new independent tasks.",
            "",
            "## New false-pass evidence",
            "",
        ]
    )
    fail_rows = []
    for r in false:
        for check in r["protected"]["failed_checks"]:
            fail_rows.append(
                [
                    r["root_label"],
                    r["task_id"],
                    r["attempt"],
                    r["run_id"],
                    check,
                    failure_category(check),
                    f"{r['trace']}:L{r['evaluation_line']}",
                ]
            )
    lines.extend(
        [
            table(
                [
                    "Root",
                    "Task",
                    "Attempt",
                    "Run ID",
                    "Failed protected check",
                    "Analyst category",
                    "Original trace evidence",
                ],
                fail_rows,
            )
            if fail_rows
            else "No confirmed new false passes with fresh visible-test evidence.",
            "",
            "Categories are interpretations of recorded failed-check names and assertion output, not causal proof. "
            "All failure details are retained in evidence.json; no evaluator reran during analysis.",
            "",
            "## Resource distributions and variance",
            "",
            "Tokens are cumulative input plus output, including cached input. Tool calls and wall seconds are measured "
            "worker-result fields (wall includes orchestration and original evaluation). USD is exclusively recorded ledger "
            "token-price upper-bound accounting, not an invoice; cached-input discounts in RunResult.cost_usd are not substituted. "
            "All decimals are truncated toward zero, never rounded up. Missing values are not replaced with zero.",
            "",
        ]
    )
    metrics = [
        ("tokens", "tokens"),
        ("tool_calls", "tool calls"),
        ("wall_seconds", "wall seconds"),
        ("ledger_usd", "USD upper bound"),
        ("api_calls", "API calls"),
    ]
    dist = []
    for label, runs in [("New main", main)] + [(key[2], g) for key, g in by_task.items()]:
        for key, name in metrics:
            values = [
                r["result"][key] if key in ("tool_calls", "wall_seconds") else r.get(key)
                for r in runs
            ]
            dist.append([label, name] + summary(values, 10 if key == "ledger_usd" else 6))
    lines.extend(
        [
            table(
                [
                    "Population/task",
                    "Per-run metric",
                    "Available n",
                    "Mean",
                    "Median",
                    "Min",
                    "Max",
                ],
                dist,
            ),
            "",
            "Every main-run resource record:",
            "",
            table(
                [
                    "Task",
                    "Attempt",
                    "Run ID",
                    "Tokens",
                    "Tool calls",
                    "Wall seconds",
                    "Ledger USD upper bound",
                ],
                [
                    [
                        r["task_id"],
                        r["attempt"],
                        r["run_id"],
                        r["tokens"],
                        r["result"]["tool_calls"],
                        fmt(r["result"]["wall_seconds"]),
                        fmt(r["ledger_usd"], 10),
                    ]
                    for r in sorted(main, key=lambda r: (r["split"], r["task_id"], r["attempt"]))
                ],
            ),
            "",
        ]
    )
    task_resources = []
    solved_tasks = []
    for (_, split, tid), group in by_task.items():
        total = resources(group)
        solved = sum(r["result"]["evaluation"] == "passed" for r in group)
        task_resources.append(
            [split, tid, len(group), solved]
            + [fmt(total[key], 10 if key == "ledger_usd" else 6) for key, _ in metrics]
        )
        if solved:
            solved_tasks.append(total)
    lines.extend(
        [
            "Per-task totals sum all main attempts of that task, including failed attempts.",
            "",
            table(
                ["Split", "Task", "Attempts", "Successful attempts"]
                + [name for _, name in metrics],
                task_resources,
            ),
            "",
            "Resources per solved task below mean each task with at least one successful main attempt, with the cumulative "
            "resources of all its attempts included. This is different from cost per successful attempt.",
            "",
            table(
                [
                    "Per solved-task metric",
                    "Available solved tasks",
                    "Mean",
                    "Median",
                    "Min",
                    "Max",
                ],
                [
                    [name]
                    + summary([t[key] for t in solved_tasks], 10 if key == "ledger_usd" else 6)
                    for key, name in metrics
                ],
            ),
            "",
        ]
    )
    successes = sum(r["result"]["evaluation"] == "passed" for r in main)
    solved_distinct = len(solved_tasks)
    lines.extend(
        [
            "For an additional study-level efficiency view, the following ratios charge all main attempts "
            "(including failures) against observed successes. They are descriptive expenditure ratios, not forecasts.",
            "",
            table(
                [
                    "Metric",
                    "All-main total",
                    "Total / successful attempt",
                    "Total / distinct task with any success",
                ],
                [
                    [
                        name,
                        fmt(result["main_resource_totals"][key], 10 if key == "ledger_usd" else 6),
                        fmt(
                            result["main_resource_totals"][key] / successes,
                            10 if key == "ledger_usd" else 6,
                        )
                        if successes
                        else "not available",
                        fmt(
                            result["main_resource_totals"][key] / solved_distinct,
                            10 if key == "ledger_usd" else 6,
                        )
                        if solved_distinct
                        else "not available",
                    ]
                    for key, name in metrics
                ],
            ),
            "",
            "## Resource stops",
            "",
        ]
    )
    stops = []
    for label, runs in [("New main", main), ("Smoke", smoke), ("All new", main + smoke)]:
        reasons = Counter(r["resource_stop"] for r in runs if r.get("resource_stop"))
        for reason, count in sorted(reasons.items()):
            group = [r for r in runs if r.get("resource_stop") == reason]
            stops.append(
                [
                    label,
                    reason,
                    count,
                    rate(sum(r["result"]["evaluation"] == "passed" for r in group), count),
                ]
            )
    lines.extend(
        [
            table(
                ["Population", "Stop reason", "Stopped runs", "Independent passes / stopped runs"],
                stops,
            ),
            "",
            table(
                ["Resource-stopped new run", "Task", "Reason", "Independent result"],
                [
                    [r["run_id"], r["task_id"], r["resource_stop"], r["result"]["evaluation"]]
                    for r in main + smoke
                    if r.get("resource_stop")
                ],
            ),
            "",
            f"Explicit main step/tool-limit stops = {sum(r.get('resource_stop') in ('step_limit', 'tool_call_limit') for r in main)}; "
            f"explicit main time-limit stops = {sum(r.get('resource_stop') in ('wall_timeout', 'sandbox_timeout') for r in main)}. "
            "A token-limit stop can happen below the numeric token cap when the next counted context cannot fit; "
            "it does not determine patch correctness. No global-budget stop occurred. The original interruption retains uncertain usage "
            "and its full reservation; recovery authorization does not resolve or rewrite it.",
            "",
            "## Reconciliation and limitations",
            "",
            table(
                ["Check", "Recorded count/status"],
                [
                    ["New worker SQLite rows", new["reconciliation"]["sqlite_runs"]],
                    ["New JSONL worker trace files", new["reconciliation"]["trace_files"]],
                    [
                        "SQLite-only / trace-only IDs",
                        f"{len(new['reconciliation']['sqlite_only'])} / {len(new['reconciliation']['trace_only'])}",
                    ],
                    ["New ledger rows", len(new["ledger"])],
                    ["New ledger states", str(dict(Counter(r["state"] for r in new["ledger"])))],
                    ["New parser/reconciliation issues", len(new["issues"])],
                ],
            ),
            "",
            "Disclosed parser/reconciliation notes: " + "; ".join(new["issues"]) + ".",
            "",
            "For every new run, SQLite result equals trace run_end; model usage sums equal worker tokens; tool-call "
            "events equal recorded tool calls; present cell payloads equal worker results; original independent evaluation "
            "agrees with the result; conditions.json equals SQLite metadata; all ledger tickets map uniquely to a worker "
            "time window and confirmed ledger tokens equal recorded worker tokens. The preserved interruption retains an additional "
            "reservation equal to its unconfirmed_tokens. Its missing cell payload is joined using the controller running-cell audit. "
            "These incomplete records are disclosed rather than treated as unexplained mismatches. The prior failed startup has no worker record and "
            "is preserved separately. No original source, task, fixture, evaluator, configuration or earlier artifact was changed.",
            "",
            "Potential limitations include authored fixture selection, prior exposure (including all dev tasks), "
            "few independent tasks, adaptive dev reuse, model alias mutability and wall-clock noise. "
            "No candidate was run or evaluated in this study, so no candidate improvement claim follows.",
            "",
            "## Candidate resume bullets",
            "",
        ]
    )
    ledger_calls = sum(r["api_calls"] for r in result["root_ledgers"])
    ledger_tokens = sum(r["confirmed_tokens"] for r in result["root_ledgers"])
    bullets = [
        (
            f"Measured a frozen coding-agent baseline across {len(main)} repeated attempts on {len(by_task)} project-authored debugging tasks; full-task outcomes were consistent within every task, while partial-check counts varied on {len(result['partial_check_variation_tasks'])} tasks.",
            "`report_repeats.py`: main run IDs, task_groups, consistent_tasks/inconsistent_tasks; `analyze.py` inventory/result_non_test/cells queries.",
        ),
        (
            f"Detected {len(false)} visible-test false passes through independent protected checks across the new recorded runs, with trace-linked failure evidence.",
            "`report_repeats.py`: numerator_denominator(false_given_visible_pass), new_false_pass_run_ids; original evaluation and post-edit reproduction events.",
        ),
        (
            f"Reconciled {ledger_calls} recorded API requests and {ledger_tokens} tokens across isolated experiment ledgers, worker SQLite records and JSONL traces.",
            "`report_repeats.py`: root_ledgers sums; `analyze.py` ledger query joined to audit tickets and worker time windows.",
        ),
    ]
    stopped = [r for r in main if r.get("resource_stop")]
    bullets.append(
        (
            f"Separated resource stops from repair correctness: {sum(r['result']['evaluation'] == 'passed' for r in stopped)} of {len(stopped)} resource-stopped main attempts still passed independent evaluation.",
            "`report_repeats.py`: resource_stop and original result.evaluation; run_end/error/evaluation trace events.",
        )
    )
    for bullet, source in bullets:
        lines.extend(
            [
                "- " + bullet,
                "",
                "  Number source: `.venv/bin/python scripts/analysis_resume/report_repeats.py`; "
                + source,
                "",
            ]
        )


def verify_output(evidence, output_dir):
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "verify.py"),
        "--evidence-dir",
        str(output_dir),
    ]
    for root in evidence["artifact_roots"]:
        command.extend(["--artifact-root", root])
    subprocess.run(command, cwd=REPO, check=True)


if __name__ == "__main__":
    data = collect()
    summary_result = write_report(data)
    # Include the finalized report in both input-fingerprint captures, then prove
    # deterministic regeneration independently for each selected root population.
    old = analyze.analyze([REPO / "artifacts"], OLD_OUT, False)
    new = analyze.analyze([Path(root) / "artifacts" for root in data[1].values()], NEW_OUT, False)
    verify_output(old, OLD_OUT)
    verify_output(new, NEW_OUT)
    print(
        json.dumps(
            {
                "main_runs": summary_result["main_run_count"],
                "tasks": summary_result["main_task_count"],
                "inconsistent_tasks": summary_result["inconsistent_tasks"],
                "rates": summary_result["rate_populations"],
                "root_ledgers": summary_result["root_ledgers"],
            },
            indent=2,
        )
    )
