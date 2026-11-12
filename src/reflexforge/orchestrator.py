import os
import time
import uuid
from pathlib import Path
from typing import Any

import openai

from reflexforge.evaluation.evaluator import Evaluator, make_patch
from reflexforge.meta.budget import BudgetExceeded
from reflexforge.sandbox.manager import (
    DockerSandbox,
    InvalidPatchError,
    SandboxError,
    SandboxFactory,
    SandboxTimeout,
)
from reflexforge.schema import RunResult, Task
from reflexforge.storage.database import Database
from reflexforge.storage.traces import Trace
from reflexforge.tasks import fixture_files
from reflexforge.worker.agent import WorkerAgent, configured_model, effective_budget, estimate_cost
from reflexforge.worker.config import AgentConfig
from reflexforge.worker.tools import WorkerTools


def run_worker(
    task: Task,
    directory: Path,
    config: AgentConfig,
    artifacts: Path,
    *,
    dry_run: bool = False,
    client: Any = None,
    factory: SandboxFactory | None = None,
    model: str | None = None,
    reflection_only: bool = False,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> RunResult:
    model = model or configured_model()
    if not dry_run and client is None and not os.getenv("OPENAI_API_KEY"):
        raise ValueError("export OPENAI_API_KEY before a live run (OPENAI_MODEL is optional)")
    estimate_cost(0, 0)
    original = fixture_files(task, directory)
    hidden_path = directory / task.hidden_test
    if hidden_path.is_symlink() or not hidden_path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("invalid evaluator path")
    hidden = hidden_path.read_text()
    budget = effective_budget(config.params, task.budget)
    run_id = uuid.uuid4().hex
    trace = Trace(artifacts / "traces" / f"{run_id}.jsonl", run_id)
    db = Database(artifacts / "experiments.sqlite3")
    result = RunResult(
        run_id=run_id,
        task_id=task.id,
        config_version=config.version,
        model=model or "unconfigured",
        synthetic=dry_run,
        termination="starting",
    )
    db.start(run_id, task.id, task.split, dry_run)
    started = time.monotonic()
    trace.event(
        "run_start",
        {
            "task": task.model_dump(exclude={"hidden_test"}),
            "synthetic": dry_run,
            "config_version": config.version,
        },
    )
    try:
        if dry_run:
            result.termination = "synthetic_plan_only"
            trace.event(
                "synthetic_plan",
                {"stages": ["sandbox", "worker", "patch", "evaluation"], "executed": False},
            )
            return result
        if factory is None:
            image = os.getenv("REFLEXFORGE_IMAGE", "reflexforge-sandbox:local")

            def factory(seconds: int, command: int) -> DockerSandbox:
                return DockerSandbox(image, seconds, command)

        api = client if client is not None else openai.OpenAI(max_retries=0)
        try:
            with factory(budget.wall_seconds, budget.command_seconds) as box:
                box.upload(original)
                if task.setup:
                    setup = box.shell(task.setup)
                    trace.event("setup_result", setup.model_dump())
                    if setup.exit_code:
                        result.termination = "setup_failed"
                        result.failure_category = "environment_setup"
                        return result
                WorkerAgent(
                    api, model, temperature=temperature, reasoning_effort=reasoning_effort
                ).run(
                    task.issue,
                    task.reproduction,
                    config,
                    WorkerTools(box, config, task.editable),
                    budget,
                    trace,
                    result,
                    reflection_only=reflection_only,
                )
                changed = {name: box.read(name) for name in task.editable}
                patch = make_patch(original, changed, task.editable)
                result.patch = patch.diff
                trace.event("patch", {"files": patch.files, "diff": patch.diff})
        finally:
            if client is None:
                api.close()
        evaluation = Evaluator(factory).evaluate(task, original, patch, hidden)
        result.evaluation = "passed" if evaluation.exit_code == 0 else "failed"
        if evaluation.exit_code and result.failure_category is None:
            result.failure_category = "incorrect_patch"
        trace.event("evaluation", evaluation.model_dump())
    except KeyboardInterrupt:
        result.termination = "interrupted"
        result.failure_category = "interrupted"
        raise
    except InvalidPatchError as exc:
        result.termination = "invalid_patch"
        result.evaluation = "failed"
        result.failure_category = "incorrect_patch"
        trace.event("error", {"type": type(exc).__name__, "message": str(exc)})
    except SandboxTimeout as exc:
        result.termination = "sandbox_timeout"
        result.failure_category = "execution_budget_exhausted"
        trace.event("error", {"type": type(exc).__name__, "message": str(exc)})
    except SandboxError as exc:
        result.termination = "sandbox_error"
        result.evaluation = "sandbox_error"
        result.failure_category = "sandbox_failure"
        trace.event("error", {"type": type(exc).__name__, "message": str(exc)})
    except BudgetExceeded as exc:
        result.termination = "budget_exhausted"
        result.failure_category = "execution_budget_exhausted"
        trace.event("error", {"type": type(exc).__name__, "message": str(exc)})
        raise
    except Exception as exc:
        result.termination = "controller_error"
        result.failure_category = "controller_failure"
        trace.event("error", {"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        result.wall_seconds = time.monotonic() - started
        result.cost_usd = (
            None
            if result.usage_incomplete
            else estimate_cost(
                result.input_tokens, result.output_tokens, result.cached_input_tokens
            )
        )
        trace.event("run_end", result.model_dump())
        db.finish(result, trace)
    return result
