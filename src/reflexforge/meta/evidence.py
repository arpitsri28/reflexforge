"""Bounded, stage-aware projections of worker-visible training evidence only."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reflexforge.schema import RunResult, Task

EVIDENCE_POLICY_VERSION = 2


@dataclass(frozen=True)
class TrainingFailure:
    run_id: str
    events: dict[int, dict[str, Any]]
    warnings: list[str]
    termination: str
    failure_category: str | None
    config_version: str
    execution: dict[str, Any]


def collect_failure(
    task: Task, result: RunResult, path: Path, *, synthetic: bool, worker_tools_only: bool = False
) -> TrainingFailure:
    if task.split != "train" or result.task_id != task.id or result.synthetic != synthetic:
        raise ValueError("only matching training runs may enter reflection")
    if result.evaluation != "failed":
        raise ValueError("only independently evaluated failures may enter reflection")
    if path.stat().st_size > 4_000_000:
        raise ValueError("training trace too large for bounded reflection")
    source, warnings = {}, []
    for index, line in enumerate(path.read_text().splitlines()):
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            warnings.append(f"malformed event {index}")
            continue
        if not isinstance(item, dict) or item.get("run_id") != result.run_id:
            warnings.append(f"mismatched event {index}")
            continue
        source[index] = item
    # Do not even project worker-like events appended after independent evaluation.
    cutoff = next(
        (i for i, e in source.items() if e.get("kind") == "evaluation"),
        len(source) + len(warnings) + 1,
    )
    calls, edits = {}, []
    for i, e in source.items():
        if i >= cutoff:
            continue
        data = e.get("data", {})
        if not isinstance(data, dict):
            continue
        if e.get("kind") == "tool_call":
            calls[data.get("call_id", f"missing-{i}")] = (i, data)
            if data.get("name") == "edit_file":
                edits.append(i)
    first_edit, last_edit = (min(edits), max(edits)) if edits else (None, None)
    projected, tests, confirmed = {}, {}, []
    for i, e in source.items():
        kind, data = e.get("kind"), e.get("data", {})
        if not isinstance(data, dict):
            continue
        stage, tool, exit_code = "inspection", data.get("name"), None
        safe = {"run_id": result.run_id, "kind": kind, "data": data}
        if kind == "run_end":
            # Only safe execution metadata. Never forward evaluation, patch, or failure text.
            safe = {
                "run_id": result.run_id,
                "kind": "termination",
                "data": {"termination": result.termination},
            }
            stage = "termination"
        elif i >= cutoff:
            continue
        elif kind == "patch":
            files = data.get("files")
            if (
                not isinstance(files, dict)
                or not set(files) <= set(task.editable)
                or not all(isinstance(v, str) for v in files.values())
            ):
                continue
            # Controller-exported worker source only; omit diff and every other field.
            safe = {"run_id": result.run_id, "kind": "final_submission", "data": {"files": files}}
            stage = "final_submission"
            if last_edit is not None and i < last_edit:
                continue
        elif kind in {"tool_call", "tool_result"}:
            call = calls.get(data.get("call_id"))
            if tool == "edit_file":
                stage = "edit_attempt" if kind == "tool_call" else "edit_failure"
                if (
                    kind == "tool_result"
                    and call
                    and call[1].get("name") == "edit_file"
                    and not data.get("is_error", True)
                    and data.get("result", {}).get("exit_code") == 0
                ):
                    confirmed.append(call[0])
                    stage = "edit_confirmation"
            if kind == "tool_result" and call:
                try:
                    args = json.loads(call[1].get("arguments", "{}"))
                except (ValueError, TypeError):
                    args = {}
                if tool == "run_tests" or (
                    tool == "run_shell" and args.get("command") == task.reproduction
                ):
                    stage = (
                        "final_test"
                        if last_edit is not None and call[0] > last_edit
                        else (
                            "baseline_test"
                            if first_edit is None or call[0] < first_edit
                            else "intermediate_test"
                        )
                    )
                    exit_code = data.get("result", {}).get("exit_code")
                    tests[i] = exit_code
            if stage == "inspection" and first_edit is not None and i > first_edit:
                stage = "late_inspection"
        elif kind == "model_response":
            if worker_tools_only:
                continue
            texts = [
                part["text"]
                for message in data.get("output", [])
                if message.get("type") == "message"
                for part in message.get("content", [])
                if part.get("type") == "output_text" and isinstance(part.get("text"), str)
            ]
            if not texts:
                continue
            safe = {
                "run_id": result.run_id,
                "kind": "worker_claim",
                "data": {"text": "\n".join(texts)},
            }
            stage = "worker_claim"
        elif kind not in {"api_error", "api_retry"}:
            continue
        projected[i] = {
            "recorded": json.dumps(safe, sort_keys=True),
            "stage": stage,
            "origin_kind": kind,
            "exit_code": exit_code,
            "call_index": calls.get(data.get("call_id"), (None,))[0],
        }
    # Late snapshots and tests must survive even when the early transcript is long.
    priorities = {
        "final_submission": 0,
        "termination": 1,
        "final_test": 2,
        "edit_attempt": 3,
        "edit_confirmation": 3,
        "edit_failure": 3,
        "intermediate_test": 4,
        "baseline_test": 4,
        "worker_claim": 5,
    }
    events, characters = {}, 0
    for i in sorted(projected, key=lambda n: (priorities.get(projected[n]["stage"], 6), -n)):
        if len(events) >= 100 or characters >= 16000:
            warnings.append("event limit reached; evidence incomplete")
            break
        row = projected[i].copy()
        encoded = row["recorded"]
        kept = encoded[: min(6000, 16000 - characters)]
        row.update(recorded=kept, truncated=len(encoded) > len(kept))
        events[i] = row
        characters += len(kept)
        if row["truncated"]:
            warnings.append(f"truncated event {i}")
    if not events:
        raise ValueError("no usable worker-visible evidence in failed trace")
    final_tests = [i for i in tests if projected[i]["stage"] == "final_test"]
    final_state = "not_run" if last_edit is not None and not final_tests else "unknown"
    if final_tests:
        code = tests[max(final_tests)]
        final_state = "passed" if code == 0 else "failed" if isinstance(code, int) else "unknown"
    execution = {
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
        "last_edit_attempt_index": last_edit,
        "confirmed_edit_indices": sorted(set(confirmed)),
        "final_submission_indices": [
            i for i, e in projected.items() if e["stage"] == "final_submission"
        ],
        "final_visible_test_indices": final_tests,
        "final_visible_test_state": final_state,
        "termination": result.termination,
        "evidence_order": "final submission, termination, final tests, edits, earlier context",
        "limits": {"events": 100, "characters": 16000, "per_event_characters": 6000},
        "residual_constraint": "Only worker-visible evidence is supplied. Independent failure details are withheld. Passing public tests or earlier failures do not establish a final residual cause.",
    }
    return TrainingFailure(
        result.run_id,
        events,
        warnings,
        result.termination,
        result.failure_category,
        result.config_version,
        execution,
    )
