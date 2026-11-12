from typing import Literal

from pydantic import Field, model_validator

from reflexforge.schema import Budget, StrictModel


class Evidence(StrictModel):
    run_id: str
    event_index: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=500)


class Diagnosis(StrictModel):
    scope: Literal["residual", "process"]
    failure_category: str = Field(min_length=1)
    root_cause: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1, max_length=20)
    suggested_strategy: str = Field(min_length=1)


class StageAssessment(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    evidence: list[Evidence] = Field(max_length=10)


class FailureAttribution(StrictModel):
    run_id: str
    original_failure: StageAssessment
    worker_changes: StageAssessment
    final_observation: StageAssessment
    final_visible_test_state: Literal["passed", "failed", "not_run", "unknown"]
    residual_status: Literal["supported", "unknown"]
    residual_cause: str | None
    residual_evidence: list[Evidence] = Field(max_length=10)
    uncertainty: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def check_uncertainty(self) -> "FailureAttribution":
        if self.residual_status == "unknown":
            if self.residual_cause is not None or self.residual_evidence:
                raise ValueError(
                    "unknown residual cause must be null, with no claimed causal evidence"
                )
        elif not self.residual_cause or not self.residual_evidence:
            raise ValueError(
                "supported residual cause requires a cause and stage-appropriate evidence"
            )
        return self


class Reflection(StrictModel):
    attributions: list[FailureAttribution] = Field(max_length=8)
    diagnoses: list[Diagnosis] = Field(max_length=10)


class Proposal(StrictModel):
    target_file: str
    change_type: Literal["modify_prompt", "modify_workflow", "upsert_skill"]
    hypothesis: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    proposed_content: str = Field(min_length=1, max_length=64000)


class OptimizationSettings(StrictModel):
    max_iterations: int = Field(default=1, ge=1, le=100)
    repetitions: int = Field(default=1, ge=1, le=20)
    max_api_calls: int = Field(default=40, ge=1)
    max_tokens: int = Field(default=100000, ge=1)
    max_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    meta_output_tokens: int = Field(default=2048, ge=128, le=8192)
    max_resource_ratio: float = Field(default=1.25, ge=1.0, le=5.0, allow_inf_nan=False)
    worker_model: str = Field(min_length=1)
    meta_model: str = Field(min_length=1)
    worker_temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    worker_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] | None = None
    suite: Literal["debug", "repobench"] = "debug"
    benchmark_version: str | None = None
    train_task_ids: list[str] | None = None
    dev_task_ids: list[str] | None = None
    execution_budget: Budget | None = None
    # Model-specific standard text input/output USD per million tokens.
    worker_prices: tuple[float, float] | None = None
    meta_prices: tuple[float, float] | None = None

    @model_validator(mode="after")
    def check_prices(self) -> "OptimizationSettings":
        import math

        for pair in (self.worker_prices, self.meta_prices):
            if pair is not None and any(not math.isfinite(p) or p < 0 for p in pair):
                raise ValueError("prices must be finite and nonnegative")
        if self.max_usd is not None and (self.worker_prices is None or self.meta_prices is None):
            raise ValueError("a USD cap requires explicit worker AND meta input/output prices")
        return self
