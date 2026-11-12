import os
from typing import Literal

from pydantic import Field, model_validator

from reflexforge.meta.schemas import OptimizationSettings
from reflexforge.schema import Budget
from reflexforge.worker.agent import configured_model


class BenchmarkSettings(OptimizationSettings):
    split: Literal["train", "dev", "test"] = "train"
    conditions: list[Literal["static", "reflection", "meta", "candidate"]] = Field(
        default_factory=lambda: ["static"], min_length=1
    )
    worker_temperature: float | None = Field(default=0.0, ge=0, le=2, allow_inf_nan=False)
    worker_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] | None = "none"
    attempts: int = Field(default=1, ge=1, le=20)
    seed: int = 2026
    run_budget: Budget = Field(
        default_factory=lambda: Budget(
            max_steps=8, max_tokens=8000, response_tokens=1024, wall_seconds=120, retry_limit=0
        )
    )

    @model_validator(mode="after")
    def check_prices(self) -> "BenchmarkSettings":
        import math

        if self.worker_prices is not None and any(
            p < 0 or not math.isfinite(p) for p in self.worker_prices
        ):
            raise ValueError("worker prices must be finite and nonnegative")
        if self.max_usd is not None and self.worker_prices is None:
            raise ValueError("benchmark USD cap requires worker input/output pricing")
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("duplicate benchmark conditions")
        return self


def configured_prices(prefix: str) -> tuple[float, float] | None:
    first, second = os.getenv(prefix + "INPUT_PRICE"), os.getenv(prefix + "OUTPUT_PRICE")
    return (float(first), float(second)) if first and second else None


def optimization_settings(**kwargs) -> OptimizationSettings:
    return OptimizationSettings(
        worker_model=configured_model(),
        meta_model=os.getenv("OPENAI_META_MODEL", "").strip() or configured_model(),
        worker_prices=configured_prices("REFLEXFORGE_"),
        meta_prices=configured_prices("REFLEXFORGE_META_"),
        **kwargs,
    )


def preflight(settings: BenchmarkSettings, task_count: int) -> dict:
    cells = task_count * settings.attempts * len(settings.conditions)
    steps = settings.run_budget.max_steps
    per_run = settings.run_budget.max_tokens
    uncapped_tokens = cells * per_run
    tokens = min(uncapped_tokens, settings.max_tokens)
    calls = min(cells * steps * 2, settings.max_api_calls)
    prices = settings.worker_prices
    return {
        "paid_requests_made": False,
        "scheduled_runs": cells,
        "max_generation_requests": min(cells * steps, settings.max_api_calls // 2),
        "max_http_calls_including_counting": calls,
        "uncapped_token_reservations": uncapped_tokens,
        "overall_token_limit": settings.max_tokens,
        "bounded_token_upper_limit": tokens,
        "potential_usd_upper_bound": None if prices is None else tokens * max(prices) / 1e6,
        "hard_usd_cap": settings.max_usd,
        "warning": "Reservation upper bounds are not measurements or a guarantee all scheduled runs fit.",
    }


def optimization_preflight(
    settings: OptimizationSettings, train_count: int, dev_count: int, budget: Budget
) -> dict:
    runs = settings.max_iterations * (train_count + 2 * dev_count * settings.repetitions)
    meta_generations = 2 * settings.max_iterations
    rates = [p for pair in (settings.worker_prices, settings.meta_prices) if pair for p in pair]
    priced = settings.worker_prices is not None and settings.meta_prices is not None
    return {
        "paid_requests_made": False,
        "max_scheduled_worker_runs": runs,
        "max_meta_generations": meta_generations,
        "max_generation_requests": min(
            runs * budget.max_steps + meta_generations, settings.max_api_calls // 2
        ),
        "max_http_calls_including_counting": min(
            runs * budget.max_steps * 2 + meta_generations * 2, settings.max_api_calls
        ),
        "worker_token_upper_bound_without_global_cap": runs * budget.max_tokens,
        "overall_reserved_token_limit": settings.max_tokens,
        "potential_usd_upper_bound": settings.max_tokens * max(rates) / 1e6 if priced else None,
        "hard_usd_cap": settings.max_usd,
        "meta_input_tokens": "Counted at runtime before generation and included in overall reservation cap.",
    }
