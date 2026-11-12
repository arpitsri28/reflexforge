import hashlib
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_meta_pilot import R1, MockMeta
from test_meta_pilot import limits as limits
from test_meta_pilot import project as project
from test_reflector_attribution import Canned, cite, real_failure, unknown

from reflexforge.meta.citations import CitationValidationError, quote_match
from reflexforge.meta.diagnostics import GenerationDiagnostics, fingerprint
from reflexforge.meta.pilot import run_pilot
from reflexforge.meta.reflector import Reflector, validate_reflection
from reflexforge.meta.schemas import Reflection


def process_output(failure, quote=None, index=None):
    index = (
        index
        if index is not None
        else next(i for i, e in failure.events.items() if e["stage"] == "termination")
    )
    quote = quote if quote is not None else failure.termination
    return {
        "attributions": [unknown(failure)],
        "diagnoses": [
            {
                "scope": "process",
                "failure_category": "observable_termination",
                "root_cause": "Execution ended; residual cause is unknown.",
                "evidence": [cite(failure, index, quote)],
                "suggested_strategy": "Check final verification status.",
            }
        ],
    }


@pytest.mark.parametrize(
    "quote,expected",
    [
        ('if ready:\n    emit("ok")', "exact_decoded_string"),
        ('if ready:\r\n    emit("ok")', "line_endings_decoded_string"),
        ('if ready:\n emit("ok")', None),
        ('if ready:\n    emit("no")', None),
        ("when ready emit ok", None),
    ],
)
def test_literal_decoding_and_only_line_ending_normalization(quote, expected):
    recorded = json.dumps(
        {
            "kind": "tool_call",
            "data": {"arguments": json.dumps({"content": 'if ready:\n    emit("ok")\n'})},
        }
    )
    assert quote not in recorded
    assert quote_match(quote, recorded) == expected


def test_exact_serialized_quotes_and_truncated_or_filtered_evidence():
    text = '{"kind": "termination", "data": {"termination": "token_limit"}}'
    assert quote_match("token_limit", text) == "exact_supplied_text"
    truncated = json.dumps(
        {"kind": "tool_call", "data": {"arguments": json.dumps({"content": "start\nEND_SENTINEL"})}}
    ).split("END_SENTINEL")[0]
    assert quote_match("END_SENTINEL", truncated) is None
    failure = real_failure("task_101")
    for index in (
        45,
        99999,
    ):  # Evaluation event was never supplied, even though the real trace contains it.
        with pytest.raises(CitationValidationError) as caught:
            Reflector(Canned(process_output(failure, "anything", index)), "mock").analyze([failure])
        assert caught.value.details["location"] == "diagnoses[0].evidence[0]"
        assert caught.value.details["run_id"] == failure.run_id
        assert caught.value.details["event_index"] == index
        assert caught.value.details["event_exists"] is False
        assert caught.value.details["reason"] == "event_not_supplied"


def test_precise_quote_mismatch_has_no_event_body_in_general_error():
    failure = real_failure("task_101")
    output = process_output(failure, "fabricated PRIVATE_QUOTE")
    with pytest.raises(CitationValidationError) as caught:
        Reflector(Canned(output), "mock").analyze([failure])
    error = caught.value
    assert error.details["location"] == "diagnoses[0].evidence[0]"
    assert error.details["event_exists"] is True
    assert error.details["reason"] == "quote_mismatch"
    assert error.details["quote_status"] == "absent_from_supplied_event"
    assert "PRIVATE_QUOTE" not in str(error)


def test_validator_uses_the_same_frozen_evidence_supplied_to_the_model():
    failure = real_failure("task_101")
    output = process_output(failure, "fabricated replacement")
    index = output["diagnoses"][0]["evidence"][0]["event_index"]

    class Mutating(Canned):
        def create(self, **kwargs):
            failure.events[index]["recorded"] = "fabricated replacement"
            return super().create(**kwargs)

    with pytest.raises(CitationValidationError, match="not present"):
        Reflector(Mutating(output), "mock").analyze([failure])


def test_raw_response_is_persisted_before_parsing_and_citation_validation(tmp_path, monkeypatch):
    failure = real_failure("task_101")
    output = process_output(failure, "wrong quote")
    diagnostic = GenerationDiagnostics(
        tmp_path / "private" / "attempt-001", pilot_id="pilot", generation_attempt=1
    )
    original = Reflection.model_validate_json

    def parse(cls, text, **kwargs):
        raw = json.loads((diagnostic.directory / "response.json").read_text())
        assert raw["output_text"] == json.dumps(output)
        assert not (diagnostic.directory / "parsing.json").exists()
        return original(text, **kwargs)

    monkeypatch.setattr(Reflection, "model_validate_json", classmethod(parse))
    with pytest.raises(CitationValidationError):
        Reflector(Canned(output), "mock").analyze([failure], diagnostics=diagnostic)
    parsed = json.loads((diagnostic.directory / "parsing.json").read_text())
    rejected = json.loads((diagnostic.directory / "validation.json").read_text())
    assert parsed["status"] == "passed" and parsed["reflection"] == output
    assert rejected["failure_category"] == "citation_validation"
    assert rejected["details"]["location"] == "diagnoses[0].evidence[0]"
    manifest = json.loads((diagnostic.directory / "manifest.json").read_text())
    assert manifest["status"] == "rejected"
    request = json.loads((diagnostic.directory / "request.json").read_text())
    payload = json.loads(request["request"]["input"][0]["content"])
    assert request["pilot_id"] == "pilot" and request["generation_attempt"] == 1
    assert request["policy"]["reflection_policy_version"] == 2
    assert request["policy"]["citation_policy_version"] == 1
    assert request["evidence_sha256"] == fingerprint(payload["failures"])


@pytest.mark.parametrize("mode", ["bad_quote", "bad_json", "incomplete", "missing_usage"])
def test_rejected_generation_audit_and_proposer_isolation(project, limits, mode):
    class Rejected(MockMeta):
        def create(self, **kwargs):
            assert kwargs["instructions"].startswith("Analyze"), "Proposer must not run"
            response = super().create(**kwargs)
            if mode == "bad_quote":
                output = json.loads(response.output_text)
                output["diagnoses"][0]["evidence"][0]["quote"] = "not present in supplied data"
                response.output_text = json.dumps(output)
            elif mode == "bad_json":
                response.output_text = "{not JSON"
            elif mode == "incomplete":
                response.status = "incomplete"
            else:
                response.usage = None
            return response

    api = Rejected()
    result = run_pilot(
        project,
        limits,
        project / "config",
        run_ids=[R1],
        experiment_ids=[],
        dev_tasks=["task_107"],
        synthetic=True,
        client=api,
        runner=lambda *a, **kw: pytest.fail("worker called"),
    )
    assert result["status"] in {"failed", "budget_exhausted"}
    audit = json.loads(Path(result["audit"]).read_text())
    directory = Path(audit["reflector_diagnostics"])
    assert len(api.payloads) == 1
    assert all(
        key not in audit for key in ("reflection", "proposal", "candidate_version", "benchmark")
    )
    assert result["usage"]["api_calls"] == 2
    raw = json.loads((directory / "response.json").read_text())
    assert raw["output_text"] and raw["label"].startswith("UNTRUSTED")
    accounting = json.loads((directory / "accounting.json").read_text())
    assert accounting["generation_delta"]["api_calls"] == 2
    assert (
        accounting["generation_delta"]["usd_upper_bound"]
        == accounting["cumulative_after"]["usd_upper_bound"]
    )
    validation = json.loads((directory / "validation.json").read_text())
    parsing = json.loads((directory / "parsing.json").read_text())
    if mode == "bad_quote":
        assert parsing["status"] == "passed" and validation["status"] == "rejected"
        assert audit["validation_error"]["event_exists"] is True
    elif mode == "missing_usage":
        # Observer saves the response before BudgetedClient rejects missing usage.
        assert raw["raw_response"]["usage"] is None
        assert accounting["cumulative_after"]["uncertain"] is True
        assert parsing["status"] == validation["status"] == "not_run"
    else:
        assert parsing["status"] == "rejected" and validation["status"] == "not_run"


def test_diagnostics_are_private_create_only_and_hash_verifiable(tmp_path):
    failure = real_failure("task_101")
    diagnostic = GenerationDiagnostics(
        tmp_path / "private" / "attempt", pilot_id="id", generation_attempt=1
    )
    assert Reflector(Canned(process_output(failure)), "mock").analyze(
        [failure], diagnostics=diagnostic
    )
    assert stat.S_IMODE(diagnostic.directory.stat().st_mode) == 0o700
    manifest = json.loads((diagnostic.directory / "manifest.json").read_text())
    assert manifest["status"] == "validated"
    before = {p: p.read_bytes() for p in diagnostic.directory.iterdir()}
    for name, expected in manifest["files_sha256"].items():
        path = diagnostic.directory / name
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    with pytest.raises(RuntimeError, match="finalized"):
        diagnostic.write("response.json", {"replacement": True})
    with pytest.raises(RuntimeError, match="finalized"):
        diagnostic.write("late-addition.json", {})
    with pytest.raises(FileExistsError):
        GenerationDiagnostics(diagnostic.directory, pilot_id="id", generation_attempt=1)
    assert {p: p.read_bytes() for p in before} == before


def test_secret_redaction_is_explicit_not_silent_raw_response_rewriting(tmp_path, monkeypatch):
    secret = "sk-unit-test-secret-for-diagnostic"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    failure = real_failure("task_101")
    output = process_output(failure, secret)
    diagnostic = GenerationDiagnostics(
        tmp_path / "private" / "attempt", pilot_id="id", generation_attempt=1
    )
    with pytest.raises(CitationValidationError):
        Reflector(Canned(output), "mock").analyze([failure], diagnostics=diagnostic)
    raw = json.loads((diagnostic.directory / "response.json").read_text())
    assert raw["secret_redaction_applied"]
    assert all(secret not in p.read_text() for p in diagnostic.directory.iterdir())


def test_decoded_exact_quotes_pass_all_existing_stage_guards():
    failure = real_failure("task_102")
    output = process_output(failure)
    # Source lines contain a newline escaped inside the supplied event JSON.
    quote = "except Exception:\n            self.broker.release(job)"
    assert quote not in failure.events[42]["recorded"]
    output["attributions"][0]["worker_changes"]["evidence"] = [cite(failure, 42, quote)]
    result = Reflector(Canned(output), "mock").analyze([failure])
    matches = validate_reflection(result, [failure])
    assert (
        next(m for m in matches if m["location"].endswith("worker_changes.evidence[0]"))[
            "match_method"
        ]
        == "exact_decoded_string"
    )


def test_failed_raw_capture_still_accounts_for_response_and_never_calls_proposer(
    project, limits, monkeypatch
):
    original = GenerationDiagnostics.capture_response

    def broken(self, response):
        self.phase = "capture"
        raise OSError("simulated storage failure")

    monkeypatch.setattr(GenerationDiagnostics, "capture_response", broken)
    api = MockMeta()
    result = run_pilot(
        project,
        limits,
        project / "config",
        run_ids=[R1],
        experiment_ids=[],
        dev_tasks=["task_107"],
        synthetic=True,
        client=api,
        runner=lambda *a, **kw: pytest.fail("worker called"),
    )
    assert result["status"] == "failed" and result["usage"]["api_calls"] == 2
    assert result["usage"]["tokens"] == 120 and result["usage"]["uncertain"] is False
    assert len(api.payloads) == 1
    audit = json.loads(Path(result["audit"]).read_text())
    assert "proposal" not in audit and "reflection" not in audit
    failure = json.loads((Path(audit["reflector_diagnostics"]) / "failure.json").read_text())
    assert failure["failure_category"] == "raw_response_persistence"
    monkeypatch.setattr(GenerationDiagnostics, "capture_response", original)


def test_unparseable_unicode_response_is_not_lost(tmp_path):
    failure = real_failure("task_101")

    class UnicodeResponse(Canned):
        def create(self, **kwargs):
            return SimpleNamespace(status="completed", output_text="\ud800")

    diagnostic = GenerationDiagnostics(
        tmp_path / "private" / "attempt", pilot_id="id", generation_attempt=1
    )
    with pytest.raises(ValueError):
        Reflector(UnicodeResponse({}), "mock").analyze([failure], diagnostics=diagnostic)
    raw = json.loads((diagnostic.directory / "response.json").read_text())
    assert raw["output_text"] == "\ud800"
    assert json.loads((diagnostic.directory / "parsing.json").read_text())["status"] == "rejected"


def test_stage_rejection_diagnostics_keep_exact_attribution_evidence_location():
    failure = real_failure("task_101")
    output = process_output(failure)
    output["attributions"][0]["final_observation"]["evidence"] = [
        cite(failure, 10, "AssertionError: 2 != 1")
    ]
    with pytest.raises(CitationValidationError) as caught:
        Reflector(Canned(output), "mock").analyze([failure])
    assert caught.value.details["location"] == "attributions[0].final_observation.evidence[0]"
    assert caught.value.details["reason"] == "wrong_stage"
    assert caught.value.details["quote_status"] == "present_but_wrong_stage"


def test_saved_rejection_can_be_reproduced_offline_without_changing_its_audit(tmp_path):
    from reflexforge.meta.evidence import TrainingFailure

    failure = real_failure("task_101")
    output = process_output(failure, "absent quotation")
    diagnostic = GenerationDiagnostics(
        tmp_path / "private" / "attempt", pilot_id="id", generation_attempt=1
    )
    with pytest.raises(CitationValidationError):
        Reflector(Canned(output), "mock").analyze([failure], diagnostics=diagnostic)
    before = {p: p.read_bytes() for p in diagnostic.directory.iterdir()}
    request = json.loads((diagnostic.directory / "request.json").read_text())
    assert request["secret_redaction_applied"] is False
    assert fingerprint(request["request"]) == request["request_sha256"]
    payload = json.loads(request["request"]["input"][0]["content"])
    failures = [
        TrainingFailure(**{**f, "events": {int(i): e for i, e in f["events"].items()}})
        for f in payload["failures"]
    ]
    raw = json.loads((diagnostic.directory / "response.json").read_text())
    parsed = Reflection.model_validate_json(raw["output_text"])
    with pytest.raises(CitationValidationError) as caught:
        validate_reflection(parsed, failures)
    recorded = json.loads((diagnostic.directory / "validation.json").read_text())
    assert caught.value.details == recorded["details"]
    assert {p: p.read_bytes() for p in before} == before
