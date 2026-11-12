"""Recovery uses recorded data; only Docker integration executes fixture code."""

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest
from conftest import ROOT

from reflexforge.benchmark.manifest import digest, load_manifest
from reflexforge.benchmark.posthoc import evaluate_recovery, prepare_recovery, recover_edits
from reflexforge.benchmark.storage import BenchmarkState
from reflexforge.benchmark.suites import benchmark_artifacts
from reflexforge.schema import CommandResult, RunResult, Task
from reflexforge.storage.database import Database
from reflexforge.storage.traces import Trace
from reflexforge.worker.config import AgentConfig

EXP = "e" * 32
RUN = "a" * 32


def events(path="cache.py", content="new", command=None):
    rows = [
        {
            "kind": "tool_call",
            "data": {
                "call_id": "edit1",
                "name": "edit_file",
                "arguments": json.dumps({"path": path, "content": content}),
            },
        },
        {
            "kind": "tool_result",
            "data": {
                "call_id": "edit1",
                "name": "edit_file",
                "is_error": False,
                "result": {"exit_code": 0, "output": "file updated"},
            },
        },
    ]
    if command:
        rows.append(
            {
                "kind": "tool_call",
                "data": {
                    "call_id": "cmd",
                    "name": command[0],
                    "arguments": json.dumps({"command": command[1]}),
                },
            }
        )
    return rows


@pytest.fixture
def task():
    return Task(
        id="task_107",
        split="dev",
        repository="repo",
        issue="fixture",
        setup="",
        reproduction="python -m unittest discover -s tests -v",
        editable=["cache.py"],
    )


def test_recovery_replays_confirmed_replacements_with_event_provenance(task):
    rows = events()
    more = events(content="last")
    for row in more:
        row["data"]["call_id"] = "edit2"
    patch, evidence = recover_edits(task, {"cache.py": "old"}, rows + more)
    assert patch.files == {"cache.py": "last"}
    assert [e["call_line"] for e in evidence] == [1, 3]
    assert [e["result_line"] for e in evidence] == [2, 4]


@pytest.mark.parametrize(
    "kind",
    [
        "unconfirmed",
        "failed",
        "outside",
        "shell",
        "test_command",
        "duplicate",
        "wrong_result",
        "no_change",
    ],
)
def test_ambiguous_or_unapproved_recovery_is_rejected(task, kind):
    rows = events()
    if kind == "unconfirmed":
        rows.pop()
    elif kind == "failed":
        rows[1]["data"]["is_error"] = True
    elif kind == "outside":
        rows = events(path="../hidden.py")
    elif kind == "shell":
        rows = events(command=("run_shell", "echo changed > cache.py"))
    elif kind == "test_command":
        rows = events(command=("run_tests", "echo changed > cache.py"))
    elif kind == "duplicate":
        rows += events()
    elif kind == "wrong_result":
        rows[1]["data"]["name"] = "read_file"
    else:
        rows = events(content="old")
    with pytest.raises(ValueError):
        recover_edits(task, {"cache.py": "old"}, rows)


@pytest.fixture
def project(tmp_path):
    """Real-shaped source fixture; no dependency on ignored historical artifacts."""
    data = tmp_path / "suites/repobench"
    (data / "benchmark").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "suites/repobench/benchmark/manifest.json", data / "benchmark/manifest.json"
    )
    manifest = load_manifest(data)
    entry = next(e for e in manifest.entries if e.id == "task_107")
    store = benchmark_artifacts(tmp_path, "repobench") / "real"
    directory = store / "experiments" / EXP
    taskdir = directory / "tasks/task_107"
    shutil.copytree(ROOT / "suites/repobench/tasks/dev/task_107", taskdir)
    task = Task.model_validate_json((taskdir / "task.json").read_text())
    shutil.copytree(ROOT / "config", directory / "configs/static")
    config = AgentConfig.load(directory / "configs/static")
    metadata = {
        "suite": "repobench",
        "synthetic": False,
        "bank_version": manifest.version,
        "entries": [entry.model_dump()],
        "image_id": "mock-image",
        "config_versions": {"static": config.version},
        "sampling": {"model": "mock-model"},
    }
    metadata["conditions_hash"] = digest(metadata)
    (directory / "conditions.json").write_text(json.dumps(metadata))
    state = BenchmarkState(store)
    with state.connect() as db:
        db.execute(
            "INSERT INTO experiments VALUES (?,0,?,'budget_exhausted')", (EXP, json.dumps(metadata))
        )
    result = RunResult(
        run_id=RUN,
        task_id=task.id,
        config_version=config.version,
        model="mock-model",
        termination="budget_exhausted",
        evaluation="not_run",
    )
    trace = Trace(directory / "runs/traces" / (RUN + ".jsonl"), RUN)
    trace.event("worker_start", {"config": config.model_dump()})
    for row in events(content="class Decisions: pass\n"):
        trace.event(row["kind"], row["data"])
    trace.event("run_end", result.model_dump())
    db = Database(directory / "runs/experiments.sqlite3")
    db.start(RUN, task.id, "dev", False)
    db.finish(result, trace)
    return tmp_path


def test_frozen_recovery_validates_source_and_does_not_rewrite_originals(project):
    store = benchmark_artifacts(project, "repobench") / "real"
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob("*") if p.is_file()
    }
    provenance, task, original, patch, hidden = prepare_recovery(project, EXP, RUN)
    assert provenance["kind"] == "post_hoc_reconstructed_patch_evaluation"
    assert provenance["llm_calls"] == 0 and provenance["promotion"] is False
    assert provenance["original_outcome"]["evaluation"] == "not_run"
    assert task.id == "task_107" and patch.files == {"cache.py": "class Decisions: pass\n"}
    assert "cache.py" in original and hidden
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before} == before


@pytest.mark.parametrize("tamper", ["task", "config", "trace", "already_evaluated", "conditions"])
def test_inconsistent_recovery_sources_are_rejected(project, tamper):
    directory = benchmark_artifacts(project, "repobench") / "real/experiments" / EXP
    if tamper == "task":
        (directory / "tasks/task_107/repo/cache.py").write_text("tampered")
    elif tamper == "config":
        (directory / "configs/static/system_prompt.md").write_text("tampered")
    elif tamper == "trace":
        trace = directory / "runs/traces" / (RUN + ".jsonl")
        trace.write_text(trace.read_text().replace(RUN, "b" * 32))
    elif tamper == "conditions":
        (directory / "conditions.json").write_text("{}")
    else:
        with sqlite3.connect(directory / "runs/experiments.sqlite3") as db:
            result = json.loads(db.execute("SELECT result FROM runs").fetchone()[0])
            result["evaluation"] = "passed"
            db.execute("UPDATE runs SET result=?", (json.dumps(result),))
    with pytest.raises((ValueError, KeyError)):
        prepare_recovery(project, EXP, RUN)


def test_posthoc_evaluation_is_separate_mock_audit_and_never_calls_llm(project, monkeypatch):
    import openai

    def forbidden(*args, **kwargs):
        raise AssertionError("LLM client constructed")

    monkeypatch.setattr(openai, "OpenAI", forbidden)
    uploads = []

    class Box:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def upload(self, files, **kwargs):
            uploads.append((files, kwargs))

        def execute(self, args):
            return CommandResult(exit_code=0, output='RF_QA {"tests_run":6,"successful":true}\n')

    result = evaluate_recovery(project, EXP, RUN, factory=lambda *args: Box(), synthetic=True)
    assert (
        result["status"] == "passed"
        and result["llm_calls"] == 0
        and result["source_records_unchanged"]
    )
    record = json.loads(Path(result["record"]).read_text())
    assert record["synthetic"] and record["original_outcome"]["evaluation"] == "not_run"
    assert record["promotion"] is False and "limitations" in record
    assert uploads[0][0]["cache.py"] == "class Decisions: pass\n"
    assert uploads[1][1] == {"evaluation": True}
    with pytest.raises(ValueError, match="synthetic"):
        evaluate_recovery(project, EXP, RUN, factory=lambda *args: Box())


@pytest.mark.docker
@pytest.mark.skipif(os.getenv("REFLEXFORGE_DOCKER_TESTS") != "1", reason="Docker opt-in required")
def test_posthoc_recovery_through_real_independent_docker_evaluator(project):
    """Disposable mocked source records, actual Docker evaluator; no API client."""
    import docker

    directory = benchmark_artifacts(project, "repobench") / "real/experiments" / EXP
    metadata_path = directory / "conditions.json"
    metadata = json.loads(metadata_path.read_text())
    client = docker.from_env(timeout=5)
    try:
        metadata["image_id"] = client.images.get(
            os.getenv("REFLEXFORGE_IMAGE", "reflexforge-sandbox:local")
        ).id
    finally:
        client.close()
    metadata["conditions_hash"] = digest(
        {k: v for k, v in metadata.items() if k != "conditions_hash"}
    )
    metadata_path.write_text(json.dumps(metadata))
    with sqlite3.connect(
        benchmark_artifacts(project, "repobench") / "real/optimization.sqlite3"
    ) as db:
        db.execute("UPDATE experiments SET settings=? WHERE id=?", (json.dumps(metadata), EXP))
    original = (directory / "tasks/task_107/repo/cache.py").read_text()
    fixed = original.replace(
        "return (document.key, action)",
        "return (principal.key, principal.revision, document.key, document.revision, action)",
    )
    trace = directory / "runs/traces" / (RUN + ".jsonl")
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    next(row for row in rows if row["kind"] == "tool_call")["data"]["arguments"] = json.dumps(
        {"path": "cache.py", "content": fixed}
    )
    trace.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = evaluate_recovery(project, EXP, RUN)
    record = json.loads(Path(result["record"]).read_text())
    assert result["status"] == "passed" and result["source_records_unchanged"]
    assert (
        record["evaluation"]["exit_code"] == 0
        and '"tests_run": 6' in record["evaluation"]["output"]
    )
    assert record["original_outcome"]["evaluation"] == "not_run" and record["llm_calls"] == 0
