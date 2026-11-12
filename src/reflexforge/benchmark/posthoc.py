"""Offline evaluation of approved edits reconstructed from a recorded interrupted run.

Never changes the source run, experiment cells, or pilot audit. No LLM client is used.
"""

import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import docker

from reflexforge.benchmark.manifest import digest, load_manifest, task_content
from reflexforge.benchmark.suites import benchmark_artifacts, dataset_root
from reflexforge.evaluation.evaluator import Evaluator, Patch, make_patch
from reflexforge.meta.reuse import contained
from reflexforge.meta.state import atomic_json
from reflexforge.meta.versioning import validate_tree
from reflexforge.sandbox.manager import DockerSandbox, SandboxFactory
from reflexforge.schema import RunResult, Task
from reflexforge.tasks import fixture_files
from reflexforge.worker.config import AgentConfig
from reflexforge.worker.tools import EditArgs


def recover_edits(
    task: Task, original: dict[str, str], events: list[dict]
) -> tuple[Patch, list[dict]]:
    """Replay only successful complete file replacements, not arbitrary shell commands."""
    calls, results, edits = {}, {}, []
    for line, event in enumerate(events, 1):
        data = event["data"]
        if event["kind"] == "tool_call":
            call_id = data["call_id"]
            if call_id in calls:
                raise ValueError("duplicate tool call ID")
            name, args = data["name"], json.loads(data["arguments"])
            if name not in {
                "list_dir",
                "read_file",
                "search_code",
                "read_skill",
                "run_tests",
                "edit_file",
            }:
                raise ValueError("cannot recover a trace with arbitrary shell/unknown actions")
            if name == "run_tests" and args.get("command") != task.reproduction:
                raise ValueError("cannot recover nonstandard test commands")
            calls[call_id] = (line, name, args)
        elif event["kind"] == "tool_result":
            call_id = data["call_id"]
            if call_id not in calls or call_id in results:
                raise ValueError("unmatched or duplicate tool result")
            if data["name"] != calls[call_id][1]:
                raise ValueError("tool result name mismatch")
            results[call_id] = (line, data)
    changed = {}
    for call_id, (line, name, args) in calls.items():
        if name != "edit_file":
            continue
        result_line, data = results.get(call_id, (None, {}))
        if data.get("is_error") is not False or data.get("result", {}).get("exit_code") != 0:
            raise ValueError("edit lacks confirmed successful completion")
        edit = EditArgs.model_validate(args)
        if edit.path not in task.editable or edit.path not in original:
            raise ValueError("recovered edit is outside source allowlist")
        changed[edit.path] = edit.content
        edits.append(
            {
                "path": edit.path,
                "call_id": call_id,
                "call_line": line,
                "result_line": result_line,
                "content_sha256": hashlib.sha256(edit.content.encode()).hexdigest(),
            }
        )
    patch = make_patch(original, changed, task.editable)
    if not patch.files:
        raise ValueError("no changed source files recovered")
    return patch, edits


def prepare_recovery(
    root: Path, experiment_id: str, run_id: str
) -> tuple[dict, Task, dict, Patch, str]:
    if any(not re.fullmatch(r"[a-f0-9]{32}", value) for value in (experiment_id, run_id)):
        raise ValueError("invalid source experiment or run ID")
    store = benchmark_artifacts(root, "repobench") / "real"
    directory = contained(store, store / "experiments" / experiment_id)
    metadata_path = contained(directory, directory / "conditions.json")
    metadata = json.loads(metadata_path.read_text())
    if metadata.get("suite") != "repobench" or metadata.get("synthetic") is not False:
        raise ValueError("post-hoc recovery requires a real RepoBench experiment")
    if (
        digest({k: v for k, v in metadata.items() if k != "conditions_hash"})
        != metadata["conditions_hash"]
    ):
        raise ValueError("source conditions hash mismatch")
    source_paths = [metadata_path]
    dbpath = contained(store, store / "optimization.sqlite3")
    with sqlite3.connect(dbpath.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT settings FROM experiments WHERE id=? AND synthetic=0", (experiment_id,)
        ).fetchone()
        if row is None or json.loads(row[0]) != metadata:
            raise ValueError("source experiment database mismatch")
    workerdb = contained(directory, directory / "runs/experiments.sqlite3")
    with sqlite3.connect(workerdb.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT task_id,split,synthetic,status,result FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
    if row is None or row[2:4] != (0, "finished"):
        raise ValueError("source must be a finished real worker record")
    result = RunResult.model_validate_json(row[4])
    if (
        result.evaluation != "not_run"
        or result.synthetic
        or result.run_id != run_id
        or result.task_id != row[0]
    ):
        raise ValueError("source run must be real and independently unevaluated")
    condition = next(
        (k for k, v in metadata["config_versions"].items() if v == result.config_version), None
    )
    if condition not in {"static", "candidate"}:
        raise ValueError("source configuration is not a paired pilot condition")
    config_path = contained(directory, directory / "configs" / condition)
    validate_tree(config_path)
    config = AgentConfig.load(config_path)
    if config.version != result.config_version or result.model != metadata["sampling"]["model"]:
        raise ValueError("source configuration/model mismatch")
    manifest = load_manifest(dataset_root(root, "repobench"), metadata["bank_version"])
    entry = next((e for e in manifest.entries if e.id == result.task_id), None)
    if (
        entry is None
        or entry.split == "test"
        or entry.split != row[1]
        or entry.model_dump() not in metadata["entries"]
    ):
        raise ValueError("invalid source task identity/split")
    taskdir = contained(directory, directory / "tasks" / result.task_id)
    taskpath = contained(taskdir, taskdir / "task.json")
    task = Task.model_validate_json(taskpath.read_text())
    if (
        task.id != result.task_id
        or task.split != entry.split
        or digest(task_content(task, taskdir)) != entry.source_hash
    ):
        raise ValueError("frozen task hash mismatch")
    original = fixture_files(task, taskdir)
    hiddenpath = contained(taskdir, taskdir / task.hidden_test)
    tracepath = contained(directory, directory / "runs/traces" / f"{run_id}.jsonl")
    if tracepath.stat().st_size > 4_000_000:
        raise ValueError("source trace too large")
    events = [json.loads(line) for line in tracepath.read_text().splitlines()]
    if any(e.get("run_id") != run_id for e in events):
        raise ValueError("trace identity mismatch")
    ends = [e["data"] for e in events if e["kind"] == "run_end"]
    starts = [e["data"] for e in events if e["kind"] == "worker_start"]
    if (
        ends != [result.model_dump()]
        or len(starts) != 1
        or starts[0]["config"] != config.model_dump()
    ):
        raise ValueError("trace/configuration/result mismatch")
    patch, edits = recover_edits(task, original, events)
    source_paths += [dbpath, workerdb, taskpath, hiddenpath, tracepath]
    source_paths += [p for p in config_path.rglob("*") if p.is_file()]
    source_paths += [p for p in (taskdir / task.repository).rglob("*") if p.is_file()]
    fingerprints = {
        str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths
    }
    provenance = {
        "kind": "post_hoc_reconstructed_patch_evaluation",
        "original_experiment_id": experiment_id,
        "original_run_id": run_id,
        "task_id": task.id,
        "condition": condition,
        "bank_version": manifest.version,
        "image_id": metadata["image_id"],
        "original_outcome": result.model_dump(),
        "confirmed_edits": edits,
        "patch_hash": digest(patch.files),
        "source_fingerprints": fingerprints,
        "promotion": False,
        "llm_calls": 0,
        "limitations": "Reconstructed from successful edit_file events, not a captured final workspace. Assumes no unlogged source writes by tests/setup. Does not complete or replace the original paired run; independent confirmation only applies to this recovered patch.",
    }
    return provenance, task, original, patch, hiddenpath.read_text()


def evaluate_recovery(
    root: Path,
    experiment_id: str,
    run_id: str,
    *,
    factory: SandboxFactory | None = None,
    synthetic: bool = False,
) -> dict[str, Any]:
    if factory is not None and not synthetic:
        raise ValueError("mock evaluator factories require synthetic provenance")
    provenance, task, original, patch, hidden = prepare_recovery(root, experiment_id, run_id)
    if factory is None:
        client = docker.from_env(timeout=5)
        try:
            image = client.images.get(provenance["image_id"]).id
        finally:
            client.close()
        if image != provenance["image_id"]:
            raise ValueError("recorded evaluator image mismatch")

        def factory(seconds, command):
            return DockerSandbox(image, seconds, command)

    identifier = uuid.uuid4().hex
    output = (
        benchmark_artifacts(root, "repobench")
        / "posthoc"
        / ("synthetic" if synthetic else "real")
        / identifier
    )
    output.mkdir(parents=True)
    record = {**provenance, "posthoc_id": identifier, "synthetic": synthetic, "status": "running"}
    atomic_json(output / "recovery.json", record)
    (output / "patch.diff").write_text(patch.diff)
    atomic_json(output / "patch.json", patch.files)
    try:
        outcome = Evaluator(factory).evaluate(task, original, patch, hidden)
        record["evaluation"] = outcome.model_dump()
        record["status"] = "passed" if outcome.exit_code == 0 else "failed"
    except BaseException as exc:
        record["status"] = "evaluation_error"
        record["error_type"] = type(exc).__name__
        raise
    finally:
        record["source_records_unchanged"] = all(
            hashlib.sha256(Path(p).read_bytes()).hexdigest() == value
            for p, value in provenance["source_fingerprints"].items()
        )
        atomic_json(output / "recovery.json", record)
    return {
        "record": str(output / "recovery.json"),
        "posthoc_id": identifier,
        "status": record["status"],
        "source_records_unchanged": record["source_records_unchanged"],
        "llm_calls": 0,
        "promotion": False,
    }
