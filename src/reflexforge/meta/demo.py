"""Explicit, deterministic synthetic optimization demo. Never a benchmark result."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from reflexforge.meta.optimizer import Optimizer
from reflexforge.meta.schemas import OptimizationSettings
from reflexforge.schema import RunResult
from reflexforge.storage.database import Database
from reflexforge.storage.traces import Trace
from reflexforge.tasks import load_tasks
from reflexforge.worker.config import AgentConfig


def synthetic_reflection(payload: dict, *, empty: bool = False) -> dict:
    """Schema-correct deterministic mock; never used by the real Reflector backend."""
    attributions, diagnoses = [], []
    for failure in payload["failures"]:
        events = failure.get("events", {0: {"recorded": "edit_file", "stage": "edit_attempt"}})
        suitable = [
            (i, e)
            for i, e in events.items()
            if e.get("stage")
            in {
                "termination",
                "final_test",
                "final_submission",
                "edit_attempt",
                "edit_confirmation",
            }
        ]
        index, event = suitable[0] if suitable else next(iter(events.items()))
        quote = "edit_file" if "edit_file" in event["recorded"] else event["recorded"][:30]
        evidence = {"run_id": failure["run_id"], "event_index": int(index), "quote": quote}
        attributions.append(
            {
                "run_id": failure["run_id"],
                "original_failure": {
                    "summary": "Original cause not established by this mock.",
                    "evidence": [],
                },
                "worker_changes": {
                    "summary": "Only recorded mock actions are available.",
                    "evidence": [],
                },
                "final_observation": {
                    "summary": "Mocked execution evidence; no residual cause inferred.",
                    "evidence": [evidence],
                },
                "residual_status": "unknown",
                "final_visible_test_state": failure.get("execution", {}).get(
                    "final_visible_test_state", "unknown"
                ),
                "residual_cause": None,
                "residual_evidence": [],
                "uncertainty": "Mock response does not establish the residual defect.",
            }
        )
        if not empty and not diagnoses:
            diagnoses.append(
                {
                    "scope": "process",
                    "failure_category": "mock_process",
                    "root_cause": "Mocked execution observation, not a hidden failure diagnosis.",
                    "evidence": [evidence],
                    "suggested_strategy": "Inspect final validation evidence.",
                }
            )
    return {"attributions": attributions, "diagnoses": diagnoses}


class SyntheticAPI:
    """Mock Responses interface available only when explicit synthetic mode is requested."""

    def __init__(self):
        self.responses = SimpleNamespace(
            input_tokens=SimpleNamespace(count=self.count), create=self.create
        )

    def count(self, **kwargs: Any) -> Any:
        return SimpleNamespace(input_tokens=100)

    def create(self, **kwargs: Any) -> Any:
        payload = json.loads(kwargs["input"][0]["content"])
        instructions = kwargs["instructions"]
        if instructions.startswith("Analyze"):
            content = synthetic_reflection(payload)
        elif instructions.startswith("Propose"):
            content = {
                "target_file": "config/system_prompt.md",
                "change_type": "modify_prompt",
                "hypothesis": "Reproduction before editing helps localization (synthetic hypothesis).",
                "justification": "Grounded in the explicitly synthetic training event.",
                "proposed_content": payload["current_config"]["system_prompt"]
                + "\nReproduce the reported failure before applying a repair.\n",
            }
        else:
            content = {}
        usage_data = {
            "input_tokens": 100,
            "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
        usage = SimpleNamespace(**usage_data, model_dump=lambda **kw: usage_data)
        return SimpleNamespace(status="completed", output_text=json.dumps(content), usage=usage)


def run_demo(root: Path, settings: OptimizationSettings, scenario: str) -> dict[str, Any]:
    if scenario not in {"accept", "reject", "no-failures"}:
        raise ValueError("unknown synthetic scenario")
    incumbent_version: str | None = None
    train = load_tasks(root / "tasks", "train")[:1]
    dev = load_tasks(root / "tasks", "dev")
    # Five explicitly synthetic comparisons exercise the conservative task-level gate.
    # They are NOT five new independent research tasks or measured outcomes.
    bank = {
        "train": train,
        "dev": [
            (dev[0][0].model_copy(update={"id": f"task_{200 + i:03}"}), dev[0][1]) for i in range(5)
        ],
    }

    def worker(
        task: Any, task_dir: Path, config: AgentConfig, artifacts: Path, *, client: Any, model: str
    ) -> RunResult:
        nonlocal incumbent_version
        if incumbent_version is None:
            incumbent_version = config.version
        request = dict(
            model=model, instructions="Synthetic worker", input=[{"role": "user", "content": "{}"}]
        )
        client.responses.input_tokens.count(**request)
        client.responses.create(**request, max_output_tokens=128)
        passed = (
            scenario == "no-failures"
            if task.split == "train"
            else config.version != incumbent_version
            if scenario == "accept"
            else config.version == incumbent_version
        )
        result = RunResult(
            run_id=uuid.uuid4().hex,
            task_id=task.id,
            config_version=config.version,
            model=model,
            synthetic=True,
            termination="completed",
            evaluation="passed" if passed else "failed",
            input_tokens=100,
            output_tokens=20,
            tool_calls=1,
            wall_seconds=1.0,
        )
        trace = Trace(artifacts / "traces" / f"{result.run_id}.jsonl", result.run_id)
        trace.event("tool_call", {"name": "edit_file", "synthetic": True})
        trace.event("run_end", result.model_dump())
        db = Database(artifacts / "experiments.sqlite3")
        db.start(result.run_id, task.id, task.split, True)
        db.finish(result, trace)
        return result

    return Optimizer(
        root, settings, synthetic=True, client=SyntheticAPI(), runner=worker, task_bank=bank
    ).run()
