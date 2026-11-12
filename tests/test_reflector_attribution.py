"""Stage attribution regressions use worker-only projections of real training traces."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import ROOT

from reflexforge.meta.evidence import collect_failure
from reflexforge.meta.reflector import Reflector, validate_reflection
from reflexforge.meta.schemas import Reflection
from reflexforge.schema import RunResult, Task


def real_failure(task_id, tools_only=True):
    directory = ROOT / "tests/fixtures/reflector" / task_id
    source = json.loads((directory / "provenance.json").read_text())
    return collect_failure(
        Task.model_validate(source["task"]),
        RunResult.model_validate(source["result"]),
        directory / "worker.jsonl",
        synthetic=False,
        worker_tools_only=tools_only,
    )


def cite(failure, index, quote):
    return {"run_id": failure.run_id, "event_index": index, "quote": quote}


def unknown(failure):
    return {
        "run_id": failure.run_id,
        "original_failure": {
            "summary": "Original behavior requires separate historical evidence.",
            "evidence": [],
        },
        "worker_changes": {
            "summary": "Recorded edits and submitted source are supplied.",
            "evidence": [],
        },
        "final_observation": {
            "summary": "Final visible evidence does not establish the residual cause.",
            "evidence": [],
        },
        "residual_status": "unknown",
        "final_visible_test_state": failure.execution["final_visible_test_state"],
        "residual_cause": None,
        "residual_evidence": [],
        "uncertainty": "Private evaluator details are withheld; no residual cause established by visible evidence.",
    }


class Canned:
    def __init__(self, output):
        self.output, self.requests = output, []
        self.responses = SimpleNamespace(
            input_tokens=SimpleNamespace(count=lambda **kw: SimpleNamespace(input_tokens=100)),
            create=self.create,
        )

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(status="completed", output_text=json.dumps(self.output))


@pytest.mark.parametrize(
    "task_id,state,last_edit,submission",
    [
        ("task_101", "not_run", 42, 44),
        ("task_102", "passed", 36, 42),
    ],
)
def test_real_training_traces_retain_final_patch_tests_and_safe_termination(
    task_id, state, last_edit, submission
):
    failure = real_failure(task_id)
    assert failure.execution["final_visible_test_state"] == state
    assert failure.execution["last_edit_attempt_index"] == last_edit
    assert failure.execution["final_submission_indices"] == [submission]
    assert list(failure.events)[0] == submission
    assert failure.events[submission]["stage"] == "final_submission"
    assert not failure.events[submission]["truncated"]
    assert any(e["stage"] == "termination" for e in failure.events.values())
    assert sum(len(e["recorded"]) for e in failure.events.values()) <= 16000
    text = json.dumps(failure.events)
    assert all(
        s not in text
        for s in (
            '"kind": "evaluation"',
            '"evaluation":',
            "test_account_and_key_delimiters_do_not_alias",
            "test_cancelled_acquisition_releases",
        )
    )
    answer = {"attributions": [unknown(failure)], "diagnoses": []}
    api = Canned(answer)
    result = Reflector(api, "mock").analyze([failure])
    assert (
        result.attributions[0].residual_status == "unknown"
        and result.attributions[0].residual_cause is None
    )
    assert not result.diagnoses
    payload = json.loads(api.requests[0]["input"][0]["content"])
    assert payload["failures"][0]["execution"]["final_visible_test_state"] == state


@pytest.mark.parametrize("task_id", ["task_101", "task_102"])
def test_early_assertion_cannot_prove_final_residual_even_with_exact_quote(task_id):
    failure = real_failure(task_id)
    attribution = unknown(failure)
    early = cite(failure, 10, "AssertionError: 2 != 1")
    assert early["quote"] in failure.events[10]["recorded"]  # Old quote-only validator accepted it.
    submission = failure.execution["final_submission_indices"][0]
    source_quote = "provider_key" if task_id == "task_101" else "except Exception"
    attribution.update(
        residual_status="supported",
        residual_cause="The original defect remains after the final patch.",
        residual_evidence=[early, cite(failure, submission, source_quote)],
    )
    output = {"attributions": [attribution], "diagnoses": []}
    with pytest.raises(ValueError, match="post-edit"):
        Reflector(Canned(output), "mock").analyze([failure])


def test_task101_intermediate_failure_cannot_be_relabelled_as_final_observation():
    failure = real_failure("task_101")
    attribution = unknown(failure)
    assert failure.events[40]["stage"] == "intermediate_test"
    attribution["final_observation"]["evidence"] = [cite(failure, 40, "AssertionError: 2 != 1")]
    with pytest.raises(ValueError, match="wrong execution stage"):
        validate_reflection(
            Reflection.model_validate({"attributions": [attribution], "diagnoses": []}), [failure]
        )


def test_task102_success_claim_is_not_test_evidence():
    failure = real_failure("task_102", tools_only=False)
    claims = [row for row in failure.events.values() if row["stage"] == "worker_claim"]
    assert claims and failure.execution["final_visible_test_state"] == "passed"
    assert "failed/incomplete jobs are released" in claims[0]["recorded"]
    # The claim cannot establish a failed post-edit test or residual cause.
    attribution = unknown(failure)
    attribution.update(
        residual_status="supported",
        residual_cause="Residual cause asserted from worker claim.",
        residual_evidence=[cite(failure, 41, "failed/incomplete jobs")],
    )
    with pytest.raises(ValueError, match="post-edit"):
        Reflector(Canned({"attributions": [attribution], "diagnoses": []}), "mock").analyze(
            [failure]
        )


def test_unknown_cannot_contain_a_claimed_cause_and_every_run_needs_attribution():
    a, b = real_failure("task_101"), real_failure("task_102")
    output = {"attributions": [unknown(a)], "diagnoses": []}
    with pytest.raises(ValueError, match="every supplied run"):
        Reflector(Canned(output), "mock").analyze([a, b])
    output["attributions"][0]["residual_cause"] = "invented cause"
    with pytest.raises(ValueError, match="must be null"):
        Reflection.model_validate(output)


def test_initial_failure_cannot_be_laundered_as_process_diagnosis():
    failure = real_failure("task_101")
    diagnosis = {
        "scope": "process",
        "failure_category": "mock",
        "root_cause": "Claim based only on original failure.",
        "evidence": [cite(failure, 10, "AssertionError: 2 != 1")],
        "suggested_strategy": "mock",
    }
    with pytest.raises(ValueError, match="late execution"):
        Reflector(
            Canned({"attributions": [unknown(failure)], "diagnoses": [diagnosis]}), "mock"
        ).analyze([failure])


@pytest.fixture
def persistent_failure(tmp_path):
    task = Task(
        id="task_001",
        repository="repo",
        issue="public contract",
        setup="",
        split="train",
        editable=["source.py"],
        reproduction="python public.py",
    )
    result = RunResult(
        run_id="mock",
        task_id=task.id,
        config_version="v",
        model="m",
        synthetic=True,
        termination="completed",
        evaluation="failed",
    )
    rows = [
        (
            "tool_call",
            {
                "call_id": "before",
                "name": "run_tests",
                "arguments": json.dumps({"command": task.reproduction}),
            },
        ),
        (
            "tool_result",
            {
                "call_id": "before",
                "name": "run_tests",
                "is_error": True,
                "result": {"exit_code": 1, "output": "initial failure"},
            },
        ),
        (
            "tool_call",
            {
                "call_id": "edit",
                "name": "edit_file",
                "arguments": json.dumps({"path": "source.py", "content": "value = 2\n"}),
            },
        ),
        (
            "tool_result",
            {
                "call_id": "edit",
                "name": "edit_file",
                "is_error": False,
                "result": {"exit_code": 0, "output": "file updated"},
            },
        ),
        (
            "tool_call",
            {
                "call_id": "after",
                "name": "run_tests",
                "arguments": json.dumps({"command": task.reproduction}),
            },
        ),
        (
            "tool_result",
            {
                "call_id": "after",
                "name": "run_tests",
                "is_error": True,
                "result": {"exit_code": 1, "output": "residual failure"},
            },
        ),
        ("patch", {"files": {"source.py": "value = 2\n"}, "diff": "PRIVATE_DIFF_SENTINEL"}),
        ("evaluation", {"output": "PRIVATE_EVALUATION_SENTINEL"}),
        (
            "run_end",
            {"termination": "completed", "patch": "PRIVATE_END_SENTINEL", "evaluation": "failed"},
        ),
    ]
    path = tmp_path / "trace.jsonl"
    path.write_text(
        "".join(
            json.dumps({"run_id": "mock", "kind": kind, "data": data}) + "\n" for kind, data in rows
        )
    )
    return task, result, path


def supported(failure):
    attribution = unknown(failure)
    attribution.update(
        residual_status="supported",
        residual_cause="The final visible check still fails for the changed source.",
        residual_evidence=[cite(failure, 5, "residual failure"), cite(failure, 6, "value = 2")],
    )
    diagnosis = {
        "scope": "residual",
        "failure_category": "visible_contract",
        "root_cause": attribution["residual_cause"],
        "evidence": copy.deepcopy(attribution["residual_evidence"]),
        "suggested_strategy": "Revisit the final source against the public contract.",
    }
    return {"attributions": [attribution], "diagnoses": [diagnosis]}


def test_supported_residual_requires_final_source_and_late_failure(persistent_failure):
    task, result, path = persistent_failure
    failure = collect_failure(task, result, path, synthetic=True)
    assert failure.execution["final_visible_test_state"] == "failed"
    output = supported(failure)
    assert Reflector(Canned(output), "mock").analyze([failure]).diagnoses[0].scope == "residual"
    text = json.dumps(failure.events)
    assert all(
        x not in text
        for x in ("PRIVATE_EVALUATION_SENTINEL", "PRIVATE_DIFF_SENTINEL", "PRIVATE_END_SENTINEL")
    )
    for evidence in (
        [cite(failure, 1, "initial failure"), cite(failure, 6, "value = 2")],
        [cite(failure, 5, "residual failure")],
    ):
        bad = copy.deepcopy(output)
        bad["attributions"][0]["residual_evidence"] = evidence
        with pytest.raises(ValueError, match="post-edit"):
            Reflector(Canned(bad), "mock").analyze([failure])
    bad = copy.deepcopy(output)
    bad["diagnoses"][0]["evidence"] = [cite(failure, 1, "initial failure")]
    with pytest.raises(ValueError, match="supported residual evidence"):
        Reflector(Canned(bad), "mock").analyze([failure])


def test_tail_priority_survives_large_early_transcript(persistent_failure):
    task, result, path = persistent_failure
    rows = path.read_text().splitlines()
    noise = [
        json.dumps(
            {
                "run_id": "mock",
                "kind": "tool_result",
                "data": {"name": "read_file", "result": {"output": "context " * 2000}},
            }
        )
        for _ in range(25)
    ]
    path.write_text("\n".join(rows[:2] + noise + rows[2:]) + "\n")
    failure = collect_failure(task, result, path, synthetic=True)
    assert failure.execution["final_visible_test_state"] == "failed"
    assert failure.events[31]["stage"] == "final_submission" and not failure.events[31]["truncated"]
    assert failure.events[30]["stage"] == "final_test"
    assert failure.warnings
    assert sum(len(e["recorded"]) for e in failure.events.values()) <= 16000


def test_attribution_quotes_must_belong_to_the_same_run():
    a, b = real_failure("task_101"), real_failure("task_102")
    output = {"attributions": [unknown(a), unknown(b)], "diagnoses": []}
    output["attributions"][0]["worker_changes"]["evidence"] = [cite(b, 42, "except Exception")]
    with pytest.raises(ValueError, match="another run"):
        Reflector(Canned(output), "mock").analyze([a, b])


def test_strict_output_schema_requires_all_fields_and_forbids_extra_properties():
    schema = Reflection.model_json_schema()
    for value in [schema, *schema["$defs"].values()]:
        if value.get("type") == "object":
            assert set(value["properties"]) == set(value["required"])
            assert value["additionalProperties"] is False


def test_extraction_reads_only_training_trace_and_preserves_sources(monkeypatch):
    paths = list((ROOT / "tests/fixtures/reflector").rglob("*"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert all(
            part not in str(path)
            for part in (
                "/tasks/dev/",
                "/tasks/test/",
                "/references/",
                "/specification.json",
                "baseline-analysis",
            )
        )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    for task in ("task_101", "task_102"):
        failure = real_failure(task)
        Reflector(Canned({"attributions": [unknown(failure)], "diagnoses": []}), "mock").analyze(
            [failure]
        )
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before} == before


def test_metadata_quotes_cannot_substitute_for_failed_output_or_final_source(persistent_failure):
    task, result, path = persistent_failure
    failure = collect_failure(task, result, path, synthetic=True)
    output = supported(failure)
    for index, quote in [(5, "exit_code"), (6, "final_submission")]:
        bad = copy.deepcopy(output)
        target = next(
            e for e in bad["attributions"][0]["residual_evidence"] if e["event_index"] == index
        )
        target["quote"] = quote
        with pytest.raises(ValueError, match="post-edit"):
            Reflector(Canned(bad), "mock").analyze([failure])


def test_truncated_final_source_cannot_support_a_residual_cause(persistent_failure):
    task, result, path = persistent_failure
    failure = collect_failure(task, result, path, synthetic=True)
    failure.events[6]["truncated"] = True
    with pytest.raises(ValueError, match="post-edit"):
        Reflector(Canned(supported(failure)), "mock").analyze([failure])


def test_claimed_grouped_process_gap_requires_action_evidence_for_each_run():
    a, b = real_failure("task_101"), real_failure("task_102")
    diagnosis = {
        "scope": "process",
        "failure_category": "mock",
        "root_cause": "Grouped execution claim.",
        "evidence": [cite(a, 44, "provider_key"), cite(b, 10, "AssertionError: 2 != 1")],
        "suggested_strategy": "mock",
    }
    with pytest.raises(ValueError, match="for each run"):
        Reflector(
            Canned({"attributions": [unknown(a), unknown(b)], "diagnoses": [diagnosis]}), "mock"
        ).analyze([a, b])


def test_evaluator_followup_events_and_unapproved_patch_files_cannot_leak(persistent_failure):
    task, result, path = persistent_failure
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[6]["data"]["files"]["hidden.py"] = "PRIVATE_UNAPPROVED_SOURCE"
    rows += [
        {
            "run_id": "mock",
            "kind": "tool_result",
            "data": {"name": "read_file", "result": {"output": "PRIVATE_AFTER_EVALUATOR"}},
        }
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    failure = collect_failure(task, result, path, synthetic=True)
    assert failure.execution["final_submission_indices"] == []
    text = json.dumps(failure.events)
    assert "PRIVATE_UNAPPROVED_SOURCE" not in text and "PRIVATE_AFTER_EVALUATOR" not in text


def test_failed_edit_is_not_marked_as_a_confirmed_change(persistent_failure):
    task, result, path = persistent_failure
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[3]["data"].update(is_error=True, result={"exit_code": 1, "output": "edit failed"})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    failure = collect_failure(task, result, path, synthetic=True)
    assert failure.events[3]["stage"] == "edit_failure"
    assert not failure.execution["confirmed_edit_indices"]


def test_model_must_report_the_recorded_final_visible_test_state():
    failure = real_failure("task_102")
    attribution = unknown(failure)
    attribution["final_visible_test_state"] = "failed"
    with pytest.raises(ValueError, match="contradicts"):
        Reflector(Canned({"attributions": [attribution], "diagnoses": []}), "mock").analyze(
            [failure]
        )


def test_alternate_run_tests_command_is_retained_as_late_public_observation(persistent_failure):
    task, result, path = persistent_failure
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[4]["data"]["arguments"] = json.dumps(
        {"command": "python -m unittest tests.test_public -v"}
    )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    failure = collect_failure(task, result, path, synthetic=True)
    assert failure.execution["final_visible_test_state"] == "failed"
    assert failure.events[5]["stage"] == "final_test"


def test_test_started_before_last_edit_is_not_proof_of_the_final_patch(persistent_failure):
    task, result, path = persistent_failure
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows = rows[:2] + [rows[4]] + rows[2:4] + rows[5:]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    failure = collect_failure(task, result, path, synthetic=True)
    assert failure.execution["last_edit_attempt_index"] == 3
    assert failure.events[5]["stage"] == "baseline_test"
    assert failure.execution["final_visible_test_state"] == "not_run"
