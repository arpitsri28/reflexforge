import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable

import docker
import openai

from reflexforge.benchmark.suites import dataset_root, optimization_artifacts
from reflexforge.evaluation.gatekeeper import PairedRun, compare
from reflexforge.meta.budget import BudgetedClient, BudgetExceeded, UsageLedger
from reflexforge.meta.diagnostics import GenerationDiagnostics
from reflexforge.meta.proposer import Proposer
from reflexforge.meta.reflector import Reflector, collect_failure, reflection_policy
from reflexforge.meta.schemas import OptimizationSettings
from reflexforge.meta.state import OptimizationState, atomic_json, exclusive_lock
from reflexforge.meta.versioning import VersionStore, candidate_snapshot
from reflexforge.orchestrator import run_worker
from reflexforge.sandbox.manager import DockerSandbox
from reflexforge.schema import RunResult, Task
from reflexforge.tasks import fixture_files, load_tasks
from reflexforge.worker.config import AgentConfig

Runner = Callable[..., RunResult]


def optimization_directory(root: Path, synthetic: bool = False, suite: str = "debug") -> Path:
    return optimization_artifacts(root, suite) / ("synthetic" if synthetic else "real")


def freeze_tasks(
    root: Path, destination: Path, settings: OptimizationSettings | None = None
) -> dict[str, list[tuple[Task, Path]]]:
    root = dataset_root(root, settings.suite if settings else "debug")
    bank: dict[str, list[tuple[Task, Path]]] = {}
    for split in ("train", "dev"):
        bank[split] = []
        selected = getattr(settings, f"{split}_task_ids", None) if settings else None
        entries = load_tasks(root / "tasks", split)
        if selected is not None and set(selected) - {t.id for t, _ in entries}:
            raise ValueError("unknown optimization task selection")
        for task, directory in entries:
            if selected is not None and task.id not in selected:
                continue
            if (root / "benchmark" / "manifest.json").exists():
                from reflexforge.benchmark.manifest import load_manifest, resolve_entry

                manifest = load_manifest(root, settings.benchmark_version if settings else None)
                entry = next(e for e in manifest.entries if e.id == task.id)
                resolve_entry(root, entry)  # Never loads private reference overlays.
            if settings and settings.execution_budget is not None:
                from reflexforge.worker.agent import effective_budget

                task = task.model_copy(
                    update={"budget": effective_budget(task.budget, settings.execution_budget)}
                )
            fixture_files(task, directory)  # Reject fixture symlinks before copying.
            hidden = directory / task.hidden_test
            if hidden.is_symlink() or not hidden.resolve().is_relative_to(directory.resolve()):
                raise ValueError("invalid evaluator test path")
            target = destination / split / task.id
            (target / task.repository).mkdir(parents=True)
            for name, content in fixture_files(task, directory).items():
                path = target / task.repository / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            (target / task.hidden_test).parent.mkdir(parents=True, exist_ok=True)
            (target / task.hidden_test).write_text(hidden.read_text())
            (target / "task.json").write_text(task.model_dump_json(indent=2))
            bank[split].append((task, target))
    if not bank["train"] or not bank["dev"]:
        raise ValueError("optimization requires nonempty train and dev splits")
    return bank


class Optimizer:
    def __init__(
        self,
        root: Path,
        settings: OptimizationSettings,
        *,
        synthetic: bool = False,
        client: Any = None,
        runner: Runner | None = None,
        task_bank: dict[str, list[tuple[Task, Path]]] | None = None,
    ):
        if not synthetic and (runner is not None or task_bank is not None):
            raise ValueError("mock task banks and runners require explicit synthetic mode")
        if synthetic and (client is None or runner is None):
            raise ValueError("synthetic optimization requires explicit mocked API and worker")
        self.root, self.settings, self.synthetic = root.resolve(), settings, synthetic
        self.client, self.runner, self.task_bank = client, runner, task_bank
        self.directory = optimization_directory(self.root, synthetic, settings.suite)
        self.state = OptimizationState(self.directory)

    def run(self) -> dict[str, Any]:
        with exclusive_lock(self.directory):
            return self._run_locked()

    def _run_locked(self) -> dict[str, Any]:
        store = VersionStore(self.directory)
        self.state.recover(store.active()[0] if store.active() else None)
        active = store.active()
        if active is None:
            store.commit(
                self.root / "config", {"kind": "baseline", "synthetic": self.synthetic}, None
            )
            active = store.active()
        assert active is not None
        experiment_id = uuid.uuid4().hex
        experiment_dir = self.directory / "experiments" / experiment_id
        experiment_dir.mkdir(parents=True)
        bank = self.task_bank or freeze_tasks(self.root, experiment_dir / "tasks", self.settings)
        if set(bank) != {"train", "dev"} or any(
            t.split != split for split, tasks in bank.items() for t, _ in tasks
        ):
            raise ValueError("optimization accepts train and dev tasks only")
        image = None
        if not self.synthetic:
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY must be configured for real optimization")
            docker_client = docker.from_env(timeout=5)
            try:
                image = docker_client.images.get(
                    os.getenv("REFLEXFORGE_IMAGE", "reflexforge-sandbox:local")
                ).id
            finally:
                docker_client.close()
        bank_version = None
        data_root = dataset_root(self.root, self.settings.suite)
        if not self.synthetic and (data_root / "benchmark" / "manifest.json").exists():
            from reflexforge.benchmark.manifest import load_manifest

            bank_version = load_manifest(data_root, self.settings.benchmark_version).version
        conditions = {
            "reflection_policy": reflection_policy(),
            "bank_version": bank_version,
            "suite": self.settings.suite,
            "settings": self.settings.model_dump(mode="json"),
            "image_id": image,
            "synthetic": self.synthetic,
            "task_fingerprint": self._task_fingerprint(bank),
        }
        atomic_json(experiment_dir / "conditions.json", conditions)
        with self.state.connect() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?, ?, ?, ?)",
                (experiment_id, int(self.synthetic), json.dumps(conditions), "running"),
            )
        ledger = UsageLedger(self.state, experiment_id, self.settings)
        api = self.client if self.client is not None else openai.OpenAI(max_retries=0)
        worker_client = BudgetedClient(
            api, ledger, "worker", self.settings.worker_model, self.settings.worker_prices
        )
        meta_client = BudgetedClient(
            api, ledger, "meta", self.settings.meta_model, self.settings.meta_prices
        )
        reflector = Reflector(
            meta_client, self.settings.meta_model, self.settings.meta_output_tokens
        )
        proposer = Proposer(meta_client, self.settings.meta_model, self.settings.meta_output_tokens)
        completed = []
        status = "finished"
        try:
            for number in range(1, self.settings.max_iterations + 1):
                iteration_id = f"{experiment_id}_{number:03}"
                data: dict[str, Any] = {
                    "synthetic": self.synthetic,
                    "incumbent": active[0],
                    "conditions": conditions,
                    "train_runs": [],
                    "dev_runs": [],
                }
                self.state.record(iteration_id, experiment_id, number, "running", data)
                try:
                    config = AgentConfig.load(active[1])
                    failures = []
                    for task, directory in bank["train"]:
                        result = self._worker(
                            task, directory, config, experiment_dir / "runs", worker_client, image
                        )
                        data["train_runs"].append(result.model_dump())
                        self.state.record(iteration_id, experiment_id, number, "running", data)
                        if result.evaluation == "failed":
                            try:
                                failures.append(
                                    collect_failure(
                                        task,
                                        result,
                                        experiment_dir
                                        / "runs"
                                        / "traces"
                                        / f"{result.run_id}.jsonl",
                                        synthetic=self.synthetic,
                                    )
                                )
                            except (OSError, ValueError) as exc:
                                data.setdefault("trace_warnings", []).append(type(exc).__name__)
                    if not failures:
                        outcome = (
                            "no_failures"
                            if all(r["evaluation"] == "passed" for r in data["train_runs"])
                            else "inconclusive"
                        )
                        data["reason"] = "no_grounded_training_failures"
                        self.state.record(iteration_id, experiment_id, number, outcome, data)
                        completed.append(iteration_id)
                        break
                    diagnostics = GenerationDiagnostics(
                        experiment_dir / "diagnostics" / iteration_id / "reflector-attempt-001",
                        pilot_id=experiment_id,
                        generation_attempt=1,
                        accounting=ledger.summary,
                        prices=self.settings.meta_prices,
                    )
                    data["reflector_diagnostics"] = str(diagnostics.directory)
                    self.state.record(iteration_id, experiment_id, number, "running", data)
                    reflection = reflector.analyze(failures, config, diagnostics=diagnostics)
                    data["reflection"] = reflection.model_dump()
                    if not reflection.diagnoses:
                        data["reason"] = "insufficient_training_evidence"
                        self.state.record(iteration_id, experiment_id, number, "inconclusive", data)
                        completed.append(iteration_id)
                        break
                    proposal = proposer.propose(config, reflection, self.state.rejected_feedback())
                    data["proposal"] = proposal.model_dump()
                    self.state.record(iteration_id, experiment_id, number, "running", data)
                    candidate_dir = self.directory / "candidates" / iteration_id / "config"
                    candidate = candidate_snapshot(active[1], candidate_dir, proposal)
                    data["candidate"] = candidate.version
                    pairs = []
                    for task_index, (task, directory) in enumerate(bank["dev"]):
                        for repetition in range(self.settings.repetitions):
                            # Alternate order to reduce systematic warm-up/order effects.
                            configs = (
                                [config, candidate]
                                if (task_index + repetition) % 2 == 0
                                else [candidate, config]
                            )
                            results = {}
                            for current in configs:
                                result = self._worker(
                                    task,
                                    directory,
                                    current,
                                    experiment_dir / "runs",
                                    worker_client,
                                    image,
                                )
                                results[current.version] = result
                                data["dev_runs"].append(result.model_dump())
                                self.state.record(
                                    iteration_id, experiment_id, number, "running", data
                                )
                            pairs.append(
                                PairedRun(
                                    task.id,
                                    repetition,
                                    results[config.version],
                                    results[candidate.version],
                                )
                            )
                    decision = compare(
                        pairs,
                        [t.id for t, _ in bank["dev"]],
                        self.settings.repetitions,
                        config.version,
                        candidate.version,
                        self.settings.worker_model,
                        self.synthetic,
                        self.settings.max_resource_ratio,
                        alpha=0.05 / self.settings.max_iterations,
                    )
                    data["decision"] = decision
                    if decision["accepted"]:
                        # Persist the exact evidence and decision before publishing the pointer.
                        self.state.record(iteration_id, experiment_id, number, "running", data)
                        version = store.commit(
                            candidate_dir,
                            {
                                "kind": "accepted",
                                "suite": self.settings.suite,
                                "bank_version": bank_version,
                                "worker_model": self.settings.worker_model,
                                "iteration_id": iteration_id,
                                "synthetic": self.synthetic,
                                "proposal": proposal.model_dump(),
                                "reflection": reflection.model_dump(),
                                "decision": decision,
                            },
                            config.version,
                        )
                        active = (version, store.snapshot(version))
                    self.state.record(
                        iteration_id, experiment_id, number, decision["outcome"], data
                    )
                    completed.append(iteration_id)
                except BaseException as exc:
                    # Persist even SystemExit; never silently retry paid work after interruption.
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        outcome, status = "interrupted", "interrupted"
                    elif isinstance(exc, BudgetExceeded):
                        outcome, status = "budget_exhausted", "budget_exhausted"
                    elif isinstance(exc, ValueError):
                        outcome, status = "invalid", "failed"
                    else:
                        outcome, status = "error", "failed"
                    data["error_type"] = type(exc).__name__
                    if isinstance(exc, (ValueError, BudgetExceeded)):
                        data["error"] = str(exc)[:1000]
                    self.state.record(iteration_id, experiment_id, number, outcome, data)
                    completed.append(iteration_id)
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    break
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
            "iterations": completed,
            "outcomes": [
                row["status"] for row in self.state.iterations() if row["id"] in completed
            ],
            "active_version": store.active()[0],
            "usage": ledger.summary(),
        }

    def _worker(
        self,
        task: Task,
        directory: Path,
        config: AgentConfig,
        artifacts: Path,
        client: Any,
        image: str | None,
    ) -> RunResult:
        if self.runner is not None:
            return self.runner(
                task, directory, config, artifacts, client=client, model=self.settings.worker_model
            )
        return run_worker(
            task,
            directory,
            config,
            artifacts,
            client=client,
            model=self.settings.worker_model,
            temperature=self.settings.worker_temperature,
            reasoning_effort=self.settings.worker_reasoning_effort,
            factory=lambda seconds, command: DockerSandbox(image, seconds, command),
        )

    @staticmethod
    def _task_fingerprint(bank: dict[str, list[tuple[Task, Path]]]) -> str:
        digest = hashlib.sha256()
        for split, entries in sorted(bank.items()):
            for task, directory in entries:
                digest.update(json.dumps(task.model_dump(), sort_keys=True).encode())
                for name, content in sorted(fixture_files(task, directory).items()):
                    digest.update(name.encode() + b"\0" + content.encode())
                digest.update((directory / task.hidden_test).read_bytes())
        return digest.hexdigest()
