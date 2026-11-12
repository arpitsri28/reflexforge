import math
import random
from collections import defaultdict
from statistics import mean
from typing import Any

from reflexforge.benchmark.runner import eligible


def aggregate(cells: list[dict[str, Any]]) -> dict[str, Any]:
    results = [c["result"] for c in cells if c.get("result") and eligible(c["result"])]
    known = [c["result"] for c in cells if c.get("result")]
    solved = sum(r["evaluation"] == "passed" for r in results)
    n = len(results)
    # Wilson interval for descriptive attempt rate; repeats require cluster analysis below.
    interval = None
    if n:
        p, z = solved / n, 1.96
        center = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        interval = [max(0, center - half), min(1, center + half)]
    cost = (
        math.fsum(r["cost_usd"] for r in known)
        if known and all(r.get("cost_usd") is not None for r in known)
        else None
    )
    tokens = sum(r["input_tokens"] + r["output_tokens"] for r in known)
    return {
        "scheduled": len(cells),
        "evaluated": n,
        "solved": solved,
        "success_rate": solved / n if n else None,
        "descriptive_attempt_wilson_95": interval,
        "infrastructure_failures": sum(c["status"] == "infrastructure_failure" for c in cells),
        "pending_or_unevaluated": sum(
            not c.get("result") or not eligible(c["result"]) for c in cells
        ),
        "confirmed_tokens": tokens,
        "cost_usd": cost,
        "tokens_per_solved": tokens / solved if solved else None,
        "cost_per_solved": cost / solved if cost is not None and solved else None,
        "tool_calls": sum(r["tool_calls"] for r in known),
        "reflection_retries": sum(r.get("reflection_retries", 0) for r in known),
        "runtime_seconds": math.fsum(r["wall_seconds"] for r in known),
    }


def exploratory(
    cells: list[dict[str, Any]], baseline: str, candidate: str, *, seed: int = 2026
) -> dict[str, Any]:
    lookup = {(c["task_id"], c["attempt"], c["condition"]): c for c in cells}
    if len(lookup) != len(cells):
        raise ValueError("duplicate paired cell keys")
    grouped = defaultdict(list)
    pairs = []
    omitted = 0
    for key, left in sorted(lookup.items()):
        task, attempt, condition = key
        if condition != baseline:
            continue
        right = lookup.get((task, attempt, candidate))
        if not right or not left.get("result") or not right.get("result"):
            omitted += 1
            continue
        if left["result"].get("model") != right["result"].get("model") or left["result"].get(
            "synthetic"
        ) != right["result"].get("synthetic"):
            raise ValueError("paired model/provenance mismatch")
        if not eligible(left["result"]) or not eligible(right["result"]):
            omitted += 1
            continue
        delta = int(right["result"]["evaluation"] == "passed") - int(
            left["result"]["evaluation"] == "passed"
        )
        grouped[task].append(delta)
        pairs.append({"task_id": task, "attempt": attempt, "delta": delta})
    deltas = [mean(values) for _, values in sorted(grouped.items())]
    interval, p_value = None, None
    if deltas:
        rng = random.Random(seed)
        samples = sorted(mean(rng.choices(deltas, k=len(deltas))) for _ in range(2000))
        interval = [samples[49], samples[1949]]
        wins, losses = sum(v > 0 for v in deltas), sum(v < 0 for v in deltas)
        n = wins + losses
        p_value = (
            min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n)
            if n
            else 1.0
        )
    inconclusive = (
        omitted > 0
        or len(deltas) < 5
        or p_value is None
        or p_value > 0.05
        or interval[0] <= 0 <= interval[1]
    )
    return {
        "baseline": baseline,
        "candidate": candidate,
        "promotion": False,
        "task_count": len(deltas),
        "paired_attempts": len(pairs),
        "omitted_pairs": omitted,
        "task_average_pass_rate_delta": mean(deltas) if deltas else None,
        "task_cluster_bootstrap_95": interval,
        "two_sided_task_sign_p": p_value,
        "inconclusive": inconclusive,
        "pairs": pairs,
        "baseline_resources": aggregate([c for c in cells if c["condition"] == baseline]),
        "candidate_resources": aggregate([c for c in cells if c["condition"] == candidate]),
        "warning": "Exploratory only; task correlations and dev adaptation limit interpretation.",
    }
