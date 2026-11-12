"""Read-only admission of recorded benchmark training failures into reflection."""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from reflexforge.benchmark.manifest import digest, load_manifest, resolve_entry
from reflexforge.benchmark.settings import BenchmarkSettings
from reflexforge.benchmark.suites import benchmark_artifacts, dataset_root
from reflexforge.meta.reflector import TrainingFailure, collect_failure
from reflexforge.meta.versioning import validate_tree
from reflexforge.schema import RunResult
from reflexforge.worker.config import AgentConfig


def contained(root: Path, path: Path) -> Path:
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("record path escapes experiment store")
    return path


@dataclass
class ReusedTraining:
    failures: list[TrainingFailure]
    sources: list[dict]


def select_training_failures(
    root: Path,
    settings: BenchmarkSettings,
    config_path: Path,
    *,
    run_ids: list[str],
    experiment_ids: list[str],
) -> ReusedTraining:
    if settings.suite != "repobench" or not (run_ids or experiment_ids):
        raise ValueError("explicit RepoBench run or experiment selectors required")
    if any(not re.fullmatch(r"[a-f0-9]{32}", x) for x in run_ids + experiment_ids):
        raise ValueError("invalid run or experiment ID")
    validate_tree(config_path)
    config = AgentConfig.load(config_path)
    expected = config.model_copy(update={"params": settings.run_budget})
    data = dataset_root(root, "repobench")
    manifest = load_manifest(data, settings.benchmark_version)
    store = benchmark_artifacts(root, "repobench") / "real"
    dbpath = contained(store, store / "optimization.sqlite3")
    # Never construct BenchmarkState here: its constructor/recovery can write records.
    with sqlite3.connect(dbpath.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        candidates = []
        for exp in dict.fromkeys(experiment_ids):
            rows = db.execute(
                "SELECT * FROM benchmark_cells WHERE experiment_id=?", (exp,)
            ).fetchall()
            if not rows:
                raise ValueError("unknown or empty source experiment")
            candidates.extend(rows)
        for run in dict.fromkeys(run_ids):
            rows = db.execute(
                "SELECT * FROM benchmark_cells WHERE json_extract(result,'$.run_id')=?", (run,)
            ).fetchall()
            if len(rows) != 1:
                raise ValueError("unknown or ambiguous source run")
            candidates.extend(rows)
        failures, sources, seen = [], [], set()
        for cell in candidates:
            if not cell["result"]:
                raise ValueError("source cell is unfinished")
            payload = json.loads(cell["result"])
            run = payload["run_id"]
            if not re.fullmatch(r"[a-f0-9]{32}", run):
                raise ValueError("invalid recorded run ID")
            if run in seen:
                continue
            seen.add(run)
            exp = cell["experiment_id"]
            if not re.fullmatch(r"[a-f0-9]{32}", exp):
                raise ValueError("invalid recorded experiment ID")
            row = db.execute("SELECT * FROM experiments WHERE id=?", (exp,)).fetchone()
            if row is None or row["synthetic"] or row["status"] != "finished":
                raise ValueError("source must be a finished real experiment")
            metadata = json.loads(row["settings"])
            recorded = metadata["settings"]
            if (
                metadata.get("synthetic") is not False
                or metadata.get("suite") != "repobench"
                or metadata.get("bank_version") != manifest.version
                or recorded.get("split") != "train"
                or recorded.get("suite") != "repobench"
                or recorded.get("worker_model") != settings.worker_model
                or recorded.get("worker_temperature") != settings.worker_temperature
                or recorded.get("worker_reasoning_effort") != settings.worker_reasoning_effort
                or recorded.get("run_budget") != settings.run_budget.model_dump()
            ):
                raise ValueError("source benchmark/model/sampling/budget provenance mismatch")
            condition = cell["condition"]
            if condition not in {"static", "reflection", "meta", "candidate"}:
                raise ValueError("invalid source condition")
            if (
                metadata.get("source_versions", {}).get(condition) != config.version
                or metadata.get("config_versions", {}).get(condition) != expected.version
            ):
                raise ValueError("source configuration mismatch")
            entry = next((e for e in manifest.entries if e.id == cell["task_id"]), None)
            if entry is None or entry.split != "train":
                raise ValueError("only training tasks may enter reflection")
            if entry.model_dump() not in metadata.get("entries", []):
                raise ValueError("source task metadata mismatch")
            task, _, _ = resolve_entry(data, entry)  # No reference/specification reads.
            if (
                payload.get("suite") != "repobench"
                or payload.get("bank_version") != manifest.version
                or payload.get("source_config_version") != config.version
                or payload.get("config_version") != expected.version
                or payload.get("model") != settings.worker_model
                or payload.get("execution_budget") != settings.run_budget.model_dump()
                or payload.get("condition") != condition
                or payload.get("attempt") != cell["attempt"]
                or payload.get("image_id") != metadata.get("image_id")
                or payload.get("synthetic") is not False
                or payload.get("task_id") != task.id
                or cell["status"] not in {"coding_failure", "solved"}
                or payload.get("usage_incomplete")
            ):
                raise ValueError("source run provenance mismatch")
            directory = contained(store, store / "experiments" / exp)
            validate_tree(directory / "configs" / condition)
            if AgentConfig.load(directory / "configs" / condition) != expected:
                raise ValueError("recorded configuration snapshot mismatch")
            workerdb = contained(directory, directory / "runs/experiments.sqlite3")
            with sqlite3.connect(workerdb.resolve().as_uri() + "?mode=ro", uri=True) as worker:
                record = worker.execute(
                    "SELECT task_id,split,synthetic,status,result FROM runs WHERE run_id=?", (run,)
                ).fetchone()
            if record is None or record[:4] != (task.id, "train", 0, "finished"):
                raise ValueError("worker database provenance mismatch")
            result = RunResult.model_validate(json.loads(record[4]))
            if any(payload.get(k) != v for k, v in result.model_dump().items() if k != "patch"):
                raise ValueError("benchmark/worker result mismatch")
            path = contained(directory, directory / "runs/traces" / f"{run}.jsonl")
            if path.stat().st_size > 4_000_000:
                raise ValueError("source trace too large")
            raw = path.read_bytes()
            events = [json.loads(line) for line in raw.splitlines()]
            if any(e.get("run_id") != run for e in events):
                raise ValueError("trace run identity mismatch")
            starts = [e["data"] for e in events if e["kind"] == "worker_start"]
            ends = [e["data"] for e in events if e["kind"] == "run_end"]
            tasks = [e["data"] for e in events if e["kind"] == "run_start"]
            if (
                len(starts) != 1
                or len(ends) != 1
                or len(tasks) != 1
                or ends[0] != result.model_dump()
                or tasks[0].get("task") != task.model_dump(exclude={"hidden_test"})
                or tasks[0].get("config_version") != expected.version
                or tasks[0].get("synthetic") is not False
                or starts[0].get("model") != settings.worker_model
                or starts[0].get("provider") != "openai"
                or starts[0].get("sampling")
                != {
                    "temperature": settings.worker_temperature,
                    "reasoning_effort": settings.worker_reasoning_effort,
                }
                or starts[0].get("budget") != settings.run_budget.model_dump()
                or starts[0].get("config") != expected.model_dump()
            ):
                raise ValueError("trace header/result provenance mismatch")
            failed = result.evaluation == "failed"
            if not failed and run in run_ids:
                raise ValueError("explicit run selector must identify a training failure")
            sources.append(
                {
                    "experiment_id": exp,
                    "run_id": run,
                    "task_id": task.id,
                    "trace_sha256": hashlib.sha256(raw).hexdigest(),
                    "result_hash": digest(result.model_dump()),
                    "used_for_reflection": failed,
                }
            )
            if failed:
                failure = collect_failure(
                    task, result, path, synthetic=False, worker_tools_only=True
                )
                if path.read_bytes() != raw:
                    raise ValueError("source trace changed during admission")
                failures.append(failure)
        if not failures or len(failures) > 8:
            raise ValueError("select between one and eight real training failures")
        return ReusedTraining(failures, sources)
