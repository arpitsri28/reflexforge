from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from reflexforge.schema import RunResult


@dataclass(frozen=True)
class PairedRun:
    task_id: str
    repetition: int
    incumbent: RunResult
    candidate: RunResult


def metrics(runs: list[RunResult]) -> dict[str, Any]:
    return {
        "attempts": len(runs),
        "solved": sum(r.evaluation == "passed" for r in runs),
        "pass_rate": sum(r.evaluation == "passed" for r in runs) / len(runs) if runs else None,
        "tokens": sum(r.input_tokens + r.output_tokens for r in runs),
        "seconds": sum(r.wall_seconds for r in runs),
        "tool_calls": sum(r.tool_calls for r in runs),
        "cost_usd": (
            sum(r.cost_usd for r in runs)
            if runs and all(r.cost_usd is not None for r in runs)
            else None
        ),
    }


def compare(
    pairs: list[PairedRun],
    task_ids: list[str],
    repetitions: int,
    incumbent_version: str,
    candidate_version: str,
    model: str,
    synthetic: bool,
    resource_ratio: float = 1.25,
    alpha: float = 0.05,
) -> dict[str, Any]:
    expected = {(task, rep) for task in task_ids for rep in range(repetitions)}
    observed = [(p.task_id, p.repetition) for p in pairs]
    decision: dict[str, Any] = {
        "accepted": False,
        "outcome": "rejected",
        "reason": "unreliable_evaluation",
        "incumbent": metrics([p.incumbent for p in pairs]),
        "candidate": metrics([p.candidate for p in pairs]),
        "synthetic": synthetic,
        "uncertainty": "Repeated attempts are grouped by task, not treated as independent tasks.",
    }
    if not expected or set(observed) != expected or len(observed) != len(expected):
        return decision
    for pair in pairs:
        for run, version in [
            (pair.incumbent, incumbent_version),
            (pair.candidate, candidate_version),
        ]:
            if (
                run.task_id != pair.task_id
                or run.config_version != version
                or run.model != model
                or run.synthetic != synthetic
                or run.usage_incomplete
                or run.evaluation not in {"passed", "failed"}
                or run.termination
                not in {"completed", "step_limit", "token_limit", "tool_call_limit"}
            ):
                return decision
    grouped: dict[str, list[int]] = defaultdict(list)
    differences = []
    for pair in pairs:
        before, after = pair.incumbent.evaluation == "passed", pair.candidate.evaluation == "passed"
        grouped[pair.task_id].append(int(after) - int(before))
        differences.append(
            {
                "task_id": pair.task_id,
                "repetition": pair.repetition,
                "incumbent": before,
                "candidate": after,
            }
        )
    decision["pairs"] = differences
    if any(value < 0 for values in grouped.values() for value in values):
        return {**decision, "reason": "success_regression"}
    for key in ("tokens", "seconds", "tool_calls", "cost_usd"):
        before, after = decision["incumbent"][key], decision["candidate"][key]
        if before is not None and after is not None and after > before * resource_ratio:
            return {**decision, "reason": f"{key}_regression"}
    wins = sum(sum(values) > 0 for values in grouped.values())
    # With no negative tasks, an exact one-sided sign test gives P=2**(-wins).
    p_value = 2.0**-wins
    decision.update(task_wins=wins, task_sign_p=p_value, alpha=alpha)
    if wins < 5 or p_value > alpha:
        return {**decision, "outcome": "inconclusive", "reason": "insufficient_task_level_evidence"}
    return {
        **decision,
        "accepted": True,
        "outcome": "accepted",
        "reason": "paired_task_improvement",
    }
