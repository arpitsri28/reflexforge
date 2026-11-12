from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Budget(StrictModel):
    max_steps: int = Field(default=20, ge=1, le=200)
    wall_seconds: int = Field(default=180, ge=1, le=3600)
    command_seconds: int = Field(default=20, ge=1, le=120)
    max_tokens: int = Field(default=30000, ge=1024)
    response_tokens: int = Field(default=2048, ge=128)
    retry_limit: int = Field(default=2, ge=0, le=5)


class Task(StrictModel):
    id: str = Field(pattern=r"^task_[0-9]{3}$")
    repository: str
    issue: str = Field(min_length=1)
    setup: str
    reproduction: str
    hidden_test: str = "hidden.py"
    evaluation_command: list[str] = Field(
        default_factory=lambda: ["python", "-I", "/evaluation/hidden.py"], min_length=1
    )
    runtime: Literal["python3.11"] = "python3.11"
    split: Literal["train", "dev", "test"]
    editable: list[str] = Field(min_length=1)
    budget: Budget = Field(default_factory=Budget)

    @model_validator(mode="after")
    def safe_paths(self) -> "Task":
        for name in [self.repository, self.hidden_test, *self.editable]:
            p = Path(name)
            if p.is_absolute() or ".." in p.parts or not p.parts:
                raise ValueError("task paths must be relative without traversal")
        if len(set(self.editable)) != len(self.editable):
            raise ValueError("editable paths must be unique")
        return self


class CommandResult(StrictModel):
    exit_code: int
    output: str


class RunResult(StrictModel):
    run_id: str
    task_id: str
    config_version: str
    model: str
    synthetic: bool = False
    termination: str
    evaluation: Literal["passed", "failed", "not_run", "sandbox_error"] = "not_run"
    failure_category: str | None = None
    steps: int = 0
    tool_calls: int = 0
    reflection_retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    usage_incomplete: bool = False
    unconfirmed_tokens: int = 0
    cost_usd: float | None = None
    wall_seconds: float = 0.0
    patch: str = ""
