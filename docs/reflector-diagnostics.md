# Reflector response auditability and literal citation validation

Reflector outputs are now captured before structured-output parsing or evidence validation.
This closes the audit gap found in pilot `82238f077c34453b93dcaec9438db51b`.
That historical response remains missing: no response was reconstructed, fabricated,
retrieved, or written into the old pilot. No paid API calls or real pilot were run
during this implementation.

## Investigation and matching correction

The old flow parsed a response, checked citations, and only then returned the reflection
to the pilot for persistence. Any parse or citation error therefore discarded the body.
The API ledger retained usage only, and `store=False` prevented relying on provider
storage for later recovery.

Event indices were already consistent: extraction preserves original zero-based indices,
and validation uses those keys, not relevance-order positions. The problem was not an
observed index conversion. Incorrect indices remain rejected.

A deterministic false-negative mechanism was reproduced: the model receives events as
serialized JSON, including function arguments serialized inside another JSON string.
A verbatim multi-line code quotation from `arguments.content` or approved exported
source need not be a substring of that double-escaped representation. The previous
validator rejected such a quotation even though the underlying exact string was supplied.
The exact quotation from the historical failed pilot is unavailable, so this mechanism
is a demonstrated possibility, not a claim about that particular response.

The new [literal matcher](/Users/arpitsrivastav/Desktop/swe_agent/src/reflexforge/meta/citations.py) accepts:
- exact substrings of the retained serialized event;
- exact substrings of string values decoded from that same complete retained event;
- exact decoded JSON function-argument values;
- CRLF/LF line-ending equivalence.

It does **not** collapse indentation, spaces or tabs; change punctuation/case/tokens;
use edit-distance matching; accept paraphrases; search another event; or load a full
trace to recover text omitted by filtering/truncation. Incomplete retained JSON is not
decoded. All existing source/late-test/stage safeguards still apply.

The Reflector prompt now explicitly tells the model to copy quotes verbatim, explains
which JSON string representations are accepted, and distinguishes zero-based indices
from display positions and one-based trace lines. Validation freezes a deep copy of
the exact evidence serialized into the request, preventing later mutation of the
caller's evidence object from changing the validation target.

## Immutable diagnostic lifecycle

[GenerationDiagnostics](/Users/arpitsrivastav/Desktop/swe_agent/src/reflexforge/meta/diagnostics.py) creates a new attempt
directory for each Reflector generation. The pilot records its path before the request.
Both the pilot and ordinary optimizer use this mechanism.

A pilot stores it at:

```text
artifacts/optimization/repobench/pilots/{real,synthetic}/PILOT_ID/
  diagnostics/reflector-attempt-001/
    request.json
    response.json
    parsing.json
    validation.json
    failure.json       # Only when rejected or failed
    accounting.json
    manifest.json
```

- `request.json`: pilot ID, attempt number, timestamp, model/request/schema, controlled
  generation settings, policy versions/prompt hash, full filtered input, event manifest
  with original indices and per-event hashes, evidence/request hashes, prices and
  accounting before the attempt.
- `response.json`: **untrusted raw SDK response envelope plus exact output_text**,
  receipt timestamp, response hash and an explicit secret-redaction flag. This is the
  SDK response body, not HTTP headers or a claim to preserve transport wire bytes.
- `parsing.json`: parsed-but-not-evidence-validated reflection, or parsing rejection
  details. Malformed/incomplete/refused outputs remain inspectable in `response.json`.
- `validation.json`: pass with citation match methods/locations, or precise rejection
  details. A stage not reached is explicitly `not_run`.
- `failure.json`: phase, failure category, exception type, message, structured citation
  details or Pydantic field locations. Schema errors omit echoed input values.
- `accounting.json`: cumulative before/after and generation deltas for calls, tokens
  and priced USD estimates. Unknown usage/reservations remain explicitly uncertain.
  An empty priced ledger starts at zero; unknown/unpriced prior usage is not treated
  as zero.
- `manifest.json`: final status and SHA-256 checksums of the other immutable artifacts.
  Finalization prevents further writes through the diagnostic writer.

The [budget client](/Users/arpitsrivastav/Desktop/swe_agent/src/reflexforge/meta/budget.py) calls the raw-response observer
immediately after the SDK returns, before usage checks. The
[structured-call path](/Users/arpitsrivastav/Desktop/swe_agent/src/reflexforge/meta/llm.py) also captures responses from
direct SDK/mock clients before parsing. Thus even a missing-usage rejection retains the
received response. If capture itself fails, the pipeline stops and still accounts for
known received usage or preserves uncertain spend; it does not retry a paid request.

Directories are owner-only (0700); files are created exclusively, fsynced and finalized
read-only (0400). Existing files/directories are never reused or overwritten, and
checksums support integrity inspection. This is application-enforced immutability,
not WORM protection against an administrator who can change filesystem permissions.

Known/recognizable API credentials are redacted before persistence. Redaction is explicitly
marked; original and stored request hashes distinguish the actual sent input from a
redacted diagnostic copy. In the normal no-secret case the body/text is retained exactly
as decoded by the SDK. JSON escaping preserves even malformed Unicode text. Never
silently treat a redacted copy as byte-identical to the original.

## Precise rejection diagnostics

Citation errors now identify a location such as:

```text
diagnoses[0].evidence[1]
attributions[1].final_observation.evidence[0]
```

Structured details include referenced run ID, zero-based event index, physical trace line,
run/event presence in the **supplied** evidence, event stage/truncation, mismatch reason,
quote length/hash and whether matching was possible. Successful validations record
whether each citation matched serialized text, decoded text, or normalized line endings.
Source/test quotations must still match the appropriate source/output fields.

General error messages do not dump quotation bodies or event contents. The exact rejected
quotation remains in the private raw/parsed artifacts for human diagnosis. Stage and
consistency errors identify their field/diagnosis location; aggregate unsupported-evidence
checks identify the relevant evidence collection rather than inventing one offending item.

## Isolation and recovery

A reflection reaches the Proposer only after parsing, every citation/stage check and
diagnostic finalization succeed. Rejected raw and parsed data are labeled as untrusted
diagnostics. No loader automatically passes them to the Proposer, reuses them as accepted
reflections, changes an old status, or starts another generation.

The saved request and response allow offline reproduction of a rejection using only the
original filtered inputs: verify the manifest hashes and redaction flags, parse the saved
response, restore JSON event keys to their integer indices, and call `validate_reflection`.
A regression test does this without any API call and confirms identical error details
and unchanged artifact bytes. Such inspection is post-hoc diagnostics, not authorization
to resume a pipeline or relabel a rejected historical result.

Train-only provenance and data filtering are unchanged. No private evaluator events,
reference solutions, development/test cases or human baseline analyses are added to meta
inputs. Diagnostic outputs are never fed back as training evidence. The active worker
configuration, task bank, Gatekeeper and spending protections remain unchanged.

The received-response and structured-output handling continues to use the
[official Responses/Structured Outputs interface](https://developers.openai.com/api/docs/guides/structured-outputs).

## Code changes

| File | Change |
|---|---|
| `meta/diagnostics.py` | Private create-only, hash-indexed lifecycle capture and accounting |
| `meta/citations.py` | Literal retained/decoded matching, line endings, structured error details |
| `meta/llm.py` | Capture before parsing, record parsing stage, scope the response observer |
| `meta/budget.py` | Observe received responses before accounting validation; account even when capture fails |
| `meta/reflector.py` | Freeze supplied evidence, clarify quotation instructions, validate against it, persist success/rejection |
| `meta/pilot.py` | Record diagnostic path before generation and precise errors; reject before Proposer |
| `meta/optimizer.py` | Wire the same capture for each normal optimization iteration |
| `tests/test_reflector_diagnostics.py` | New audit/matching/recovery regressions |
| `tests/test_meta.py` | Exercise raw capture through official SDK with MockTransport |

Attribution/evidence policies remain v2; new metadata identifies `citation_policy_version: 1`
and `diagnostic_format_version: 1`, with the new exact prompt hash. Historical policy
metadata is not rewritten.

## Preflight for a future explicitly authorized pilot

The following preflight was run without paid calls:

```bash
.venv/bin/reflexforge meta-pilot \
  --run-ids 2c1b9b2afdbf4039a7342df938ce154d,5563b7195e674d4f976e06f82442ec42 \
  --dev-tasks task_108 \
  --max-tokens 200000 --max-api-calls 200 --max-usd 0.50
```

It records the new matcher/diagnostic policy and prompt hash. Task_108 still has no
worker exposure from the failed previous pilot. Do not add `--execute` until a new paid
attempt is explicitly authorized. The existing workflow still stops before Proposer if
reflection is invalid or contains no grounded diagnosis; it never forces a proposal.

No attempt was made to manufacture the missing response from pilot
`82238f077c34453b93dcaec9438db51b`, and no new real pilot was started.



## Verification results

- `.venv/bin/pytest tests/test_reflector_diagnostics.py tests/test_reflector_attribution.py tests/test_meta.py tests/test_meta_pilot.py -q`:
  **117 passed**, including the final per-generation cost-accounting check.
- `REFLEXFORGE_DOCKER_TESTS=1 .venv/bin/pytest -q`: **281 passed** in 65.53 seconds.
- Twenty new diagnostic/citation regression cases cover exact/decoded quotations, CRLF,
  rejected paraphrases/indentation/token changes, bad indices, filtered/truncated evidence,
  pre-parse persistence, Proposer isolation, missing usage, storage failures, malformed
  Unicode, private immutable artifacts, redaction and offline rejection reproduction.
- The existing official OpenAI Python SDK/MockTransport test now verifies raw-response
  capture and per-generation accounting. All live LLM HTTP is forbidden by the suite.
- Ruff lint and formatting checks pass (64 files).
- The new task_108 preflight passes without constructing an API client. Caps remain
  200,000 tokens, 200 calls and $0.50; per-worker limits remain unchanged.
- **513 original configuration, task, trace, database and audit files retain their hashes.**
- The old failed pilot still has no manufactured diagnostic response. No paid API call,
  real pilot, candidate generation/evaluation, or active configuration modification occurred.
