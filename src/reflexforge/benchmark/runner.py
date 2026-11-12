import json
import os
import random
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

import docker
import openai
import yaml

from reflexforge.benchmark.manifest import Entry, digest, load_manifest, resolve_entry
from reflexforge.benchmark.settings import BenchmarkSettings, preflight
from reflexforge.benchmark.storage import BenchmarkState
from reflexforge.benchmark.suites import benchmark_artifacts, dataset_root, optimization_artifacts
from reflexforge.meta.budget import BudgetedClient, BudgetExceeded, UsageLedger
from reflexforge.meta.state import atomic_json, exclusive_lock
from reflexforge.meta.versioning import VersionStore, validate_tree
from reflexforge.orchestrator import run_worker
from reflexforge.sandbox.manager import DockerSandbox
from reflexforge.tasks import fixture_files
from reflexforge.worker.config import AgentConfig


def eligible(result: dict[str, Any]) -> bool:
    return (
        result.get("evaluation") in {"passed", "failed"}
        and result.get("termination")
        in {"completed", "step_limit", "token_limit", "tool_call_limit", "invalid_patch"}
        and not result.get("usage_incomplete", False)
    )


def classify(result: dict[str, Any]) -> str:
    if eligible(result):
        return "solved" if result["evaluation"] == "passed" else "coding_failure"
    return (
        "infrastructure_failure"
        if result.get("termination")
        in {"sandbox_error", "controller_error", "setup_failed", "api_error", "missing_usage"}
        else "unevaluated"
    )


class BenchmarkRunner:
    def __init__(
        self,
        root: Path,
        settings: BenchmarkSettings,
        *,
        synthetic: bool = False,
        client: Any = None,
        runner: Callable | None = None,
        shared_ledger: UsageLedger | None = None,
    ):
        if runner is not None and not synthetic:
            raise ValueError("injected runners require synthetic provenance")
        if synthetic and (client is None or runner is None):
            raise ValueError("synthetic execution requires explicit mocked clients and runners")
        self.root, self.settings, self.synthetic = root.resolve(), settings, synthetic
        self.client, self.runner = client, runner
        if shared_ledger is not None and client is None:
            raise ValueError("a shared ledger requires an explicit client")
        if shared_ledger is not None and any(
            getattr(shared_ledger.settings, field) != getattr(settings, field)
            for field in ("max_api_calls", "max_tokens", "max_usd", "worker_model", "worker_prices")
        ):
            raise ValueError("shared ledger limits/model/pricing mismatch")
        self.shared_ledger = shared_ledger
        self.dataset = dataset_root(self.root, settings.suite)
        self.directory = benchmark_artifacts(self.root, settings.suite) / (
            "synthetic" if synthetic else "real"
        )
        self.state = BenchmarkState(self.directory)

    def run(
        self,
        *,
        task_ids: list[str] | None = None,
        config_path: Path | None = None,
        optimized_version: str | None = None,
        bank_version: str | None = None,
        final: bool = False,
        candidate_config_path: Path | None = None,
    ) -> dict[str, Any]:
        manifest = load_manifest(self.dataset, bank_version)
        if getattr(manifest, "suite", "debug") != self.settings.suite:
            raise ValueError("benchmark suite mismatch")
        entries = [
            e
            for e in manifest.entries
            if e.split == self.settings.split and (task_ids is None or e.id in task_ids)
        ]
        if not entries or task_ids is not None and set(task_ids) != {e.id for e in entries}:
            raise ValueError("unknown task subset or split mismatch")
        if self.settings.split == "test" and not final:
            raise ValueError("held-out evaluation requires explicit --final")
        if len(set(self.settings.conditions)) != len(self.settings.conditions):
            raise ValueError("duplicate conditions")
        with exclusive_lock(self.directory):
            self.state.recover()
            return self._run(
                entries, manifest.version, config_path, optimized_version, candidate_config_path
            )

    def _run(
        self,
        entries: list[Entry],
        bank_version: str,
        config_path: Path | None,
        optimized_version: str | None,
        candidate_config_path: Path | None = None,
    ) -> dict[str, Any]:
        experiment_id = uuid.uuid4().hex
        work = self.directory / "experiments" / experiment_id
        work.mkdir(parents=True)
        configs, source_versions = {}, {}
        source = (
            config_path or self.root / "config"
        )  # Static baseline never silently uses optimized active config.
        for condition in self.settings.conditions:
            current = source
            if condition == "candidate":
                if candidate_config_path is None:
                    raise ValueError("exploratory candidate requires --candidate-config")
                current = candidate_config_path
                validate_tree(current)
                proposed, base = AgentConfig.load(current), AgentConfig.load(source)
                if proposed.params != base.params or proposed.tools != base.tools:
                    raise ValueError("exploratory candidates cannot alter budgets or tools")
            if condition == "meta":
                if optimized_version is None:
                    raise ValueError(
                        "meta condition requires --optimized-version from real accepted history"
                    )
                store = VersionStore(
                    optimization_artifacts(self.root, self.settings.suite) / "real"
                )
                record = next(
                    (r for r in store.history() if r["version"] == optimized_version), None
                )
                if record is None or record["kind"] != "accepted" or record.get("synthetic"):
                    raise ValueError(
                        "meta condition must use a genuinely accepted real configuration"
                    )
                if (
                    record.get("bank_version") != bank_version
                    or record.get("worker_model") != self.settings.worker_model
                ):
                    raise ValueError("optimized configuration model/task-bank version mismatch")
                current = store.snapshot(optimized_version)
            validate_tree(current)
            source_versions[condition] = AgentConfig.load(current).version
            destination = work / "configs" / condition
            destination.parent.mkdir(exist_ok=True)
            shutil.copytree(current, destination)
            (destination / "params.yaml").write_text(
                yaml.safe_dump(self.settings.run_budget.model_dump())
            )
            configs[condition] = AgentConfig.load(destination)
        baseline = next(iter(configs.values()))
        if any(c.params != baseline.params or c.tools != baseline.tools for c in configs.values()):
            raise ValueError("comparison tools or budgets differ")
        bank = []
        qa_images = set()
        for entry in entries:
            task, directory, _ = resolve_entry(self.dataset, entry)
            if not self.synthetic:
                qa_path = (
                    benchmark_artifacts(self.root, self.settings.suite)
                    / "qa"
                    / bank_version
                    / f"{entry.id}.json"
                )
                qa = json.loads(qa_path.read_text())
                if (
                    not qa.get("valid")
                    or (
                        self.settings.suite == "repobench"
                        and qa.get("manifest_hash") != bank_version
                    )
                    or qa.get("source_hash") != entry.source_hash
                    or qa.get("reference_hash") != entry.reference_hash
                ):
                    raise ValueError(
                        "fixture QA missing or out of date; run benchmark validate first"
                    )
            if not self.synthetic:
                qa_images.add(qa.get("image_id"))
            target = work / "tasks" / entry.id
            (target / task.repository).mkdir(parents=True)
            for name, content in fixture_files(task, directory).items():
                path = target / task.repository / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            (target / task.hidden_test).parent.mkdir(parents=True, exist_ok=True)
            (target / task.hidden_test).write_text((directory / task.hidden_test).read_text())
            (target / "task.json").write_text(task.model_dump_json())
            bank.append((task, target))
        image = None
        if not self.synthetic:
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is required")
            client = docker.from_env(timeout=30)
            try:
                image = client.images.get(
                    os.getenv("REFLEXFORGE_IMAGE", "reflexforge-sandbox:local")
                ).id
            finally:
                client.close()
            if qa_images != {image}:
                raise ValueError(
                    "fixture QA image mismatch; revalidate with the selected sandbox image"
                )
        metadata = {
            "settings": self.settings.model_dump(mode="json"),
            "suite": self.settings.suite,
            "bank_version": bank_version,
            "entries": [e.model_dump() for e in entries],
            "image_id": image,
            "source_versions": source_versions,
            "config_versions": {k: c.version for k, c in configs.items()},
            "sampling": {
                "temperature": self.settings.worker_temperature,
                "reasoning_effort": self.settings.worker_reasoning_effort,
                "model": self.settings.worker_model,
            },
            "synthetic": self.synthetic,
            "preflight": preflight(self.settings, len(entries)),
        }
        if self.shared_ledger is not None:
            metadata["shared_budget_experiment_id"] = self.shared_ledger.experiment_id
        metadata["conditions_hash"] = digest(metadata)
        atomic_json(work / "conditions.json", metadata)
        with self.state.connect() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?, ?, ?, ?)",
                (experiment_id, int(self.synthetic), json.dumps(metadata), "running"),
            )
            for task, _ in bank:
                for attempt in range(self.settings.attempts):
                    for condition in self.settings.conditions:
                        db.execute(
                            "INSERT INTO benchmark_cells VALUES (?, ?, ?, ?, ?, NULL)",
                            (experiment_id, task.id, attempt, condition, "pending"),
                        )
        ledger = self.shared_ledger or UsageLedger(self.state, experiment_id, self.settings)
        if self.shared_ledger is not None:
            atomic_json(work / "shared-budget.json", {"experiment_id": ledger.experiment_id})
        api = self.client if self.client is not None else openai.OpenAI(max_retries=0)
        wrapped = BudgetedClient(
            api, ledger, "worker", self.settings.worker_model, self.settings.worker_prices
        )
        status = "finished"
        try:
            for task_index, (task, directory) in enumerate(bank):
                for attempt in range(self.settings.attempts):
                    order = list(self.settings.conditions)
                    random.Random(self.settings.seed + task_index + attempt).shuffle(order)
                    for condition in order:
                        self.state.save_cell(experiment_id, task.id, attempt, condition, "running")
                        try:
                            result = (self.runner or run_worker)(
                                task,
                                directory,
                                configs[condition],
                                work / "runs",
                                client=wrapped,
                                model=self.settings.worker_model,
                                reflection_only=condition == "reflection",
                                temperature=self.settings.worker_temperature,
                                reasoning_effort=self.settings.worker_reasoning_effort,
                                factory=lambda seconds, command: DockerSandbox(
                                    image, seconds, command
                                ),
                            )
                        except BudgetExceeded:
                            self.state.save_cell(
                                experiment_id, task.id, attempt, condition, "budget_exhausted"
                            )
                            raise
                        payload = {
                            **result.model_dump(),
                            "suite": self.settings.suite,
                            "bank_version": bank_version,
                            "source_config_version": source_versions[condition],
                            "execution_budget": configs[condition].params.model_dump(),
                            "condition": condition,
                            "attempt": attempt,
                            "image_id": image,
                        }
                        if (
                            result.synthetic != self.synthetic
                            or result.model != self.settings.worker_model
                            or result.config_version != configs[condition].version
                        ):
                            raise ValueError("worker provenance/model/config mismatch")
                        self.state.save_cell(
                            experiment_id, task.id, attempt, condition, classify(payload), payload
                        )
                        if ledger.summary()["uncertain"]:
                            raise BudgetExceeded(
                                "uncertain usage blocks further benchmark requests"
                            )
        except BudgetExceeded:
            status = "budget_exhausted"
        except BaseException as exc:
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "error"
            with self.state.connect() as db:
                db.execute(
                    "UPDATE benchmark_cells SET status=? WHERE experiment_id=? AND status='running'",
                    (status, experiment_id),
                )
            self.state.trace.event(
                "benchmark_error", {"experiment_id": experiment_id, "type": type(exc).__name__}
            )
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        finally:
            with self.state.connect() as db:
                db.execute("UPDATE experiments SET status=? WHERE id=?", (status, experiment_id))
            if self.client is None:
                api.close()
        return {
            "experiment_id": experiment_id,
            "suite": self.settings.suite,
            "synthetic": self.synthetic,
            "status": status,
            "bank_version": bank_version,
            "previously_exposed_task_ids": [e.id for e in entries if e.prior_agent_exposure],
            "usage": ledger.summary(),
            "cells": len(self.state.cells(experiment_id)),
        }
