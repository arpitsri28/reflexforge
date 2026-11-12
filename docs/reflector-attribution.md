# Reflector failure attribution: policy version 2

The Reflector previously accepted quotations establishing original repository defects as
explanations of the worker's final failed submission. The update separates execution
stages and requires explicit uncertainty when the public trace does not establish the
remaining cause. No paid LLM calls or new real experiments were run during implementation.
The active worker configuration, historical traces, audits and outcomes are unchanged.

## Investigation

The previous prompt requested recurring patterns and exact quotations but did not require
separating the original failure from the final patch. Its validator checked only that the
run/event existed and that the quotation appeared in the retained text. Neither check
established that an early assertion still applied after subsequent edits.

The extraction paths had different problems:

| Previous path | Observed evidence on both historical training traces |
|---|---|
| Ordinary optimizer extraction | Copied model-response tool arguments as well as tool calls, reached its 16,000-character prefix limit at event index 29, and omitted all later edits/tests. |
| Pilot/reuse extraction | Removed duplicate model responses and retained all 28/26 worker tool events without truncation. Nevertheless it kept chronological order, omitted final exported source and quotable termination context, and supplied no stage labels or explicit final-test state. |

The latest real pilot's saved reflection inputs confirm the second case: the late edits
and tests were present. Thus prefix truncation alone cannot explain the repeated pilot
misattribution. Missing stage instructions, absent final submission snapshots and
quote-presence-only validation were central problems.

Concrete observable boundaries, with zero-based event indices:

| Training run | Last edit request | Final exported source | Last visible test | Final visible test state |
|---|---:|---:|---|---|
| task_101 / `2c1b9b2afdbf4039a7342df938ce154d` | 42 | 44 | event 40 failed **before** the final edit | `not_run` after final edit |
| task_102 / `5563b7195e674d4f976e06f82442ec42` | 36 | 42 | event 40 passed **after** the final edit | `passed` |

The initial assertion at index 10 is historical baseline evidence in both runs.
For task_101, the intermediate failing retest at index 40 cannot establish failure of
the later payment edit. For task_102, the final visible test passed, so its earlier
duplicate-claim assertion is not proof of a remaining duplicate-claim bug.

Original sources:
[task_101 final edit](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/real/experiments/2508458d048f41489d1cc51cb6fea948/runs/traces/2c1b9b2afdbf4039a7342df938ce154d.jsonl:43),
[task_101 exported source](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/real/experiments/2508458d048f41489d1cc51cb6fea948/runs/traces/2c1b9b2afdbf4039a7342df938ce154d.jsonl:45),
[task_102 late visible tests](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/real/experiments/9fd09c6ad0f14d74913bca37107588dd/runs/traces/5563b7195e674d4f976e06f82442ec42.jsonl:41),
[task_102 exported source](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/real/experiments/9fd09c6ad0f14d74913bca37107588dd/runs/traces/5563b7195e674d4f976e06f82442ec42.jsonl:43).
Physical JSONL line number = zero-based event index + 1.

## Evidence extraction changes

The new [evidence collector](/Users/arpitsrivastav/Desktop/swe_agent/src/reflexforge/meta/evidence.py) is still exposed
through the existing `collect_failure` import. Train-only, matching run/provenance and
independently failed outcome checks remain in place. The pilot's source-admission checks
for suite, bank, model, configuration, sampling, budget and cross-record consistency
remain unchanged.

The collector now:

1. Reads the bounded training trace before selecting evidence, rather than taking its
   first prefix. It removes duplicate function-call model responses.
2. Labels baseline/intermediate/final test results, edit requests, confirmed/failed edits,
   final exported source, optional worker claims and termination. Confirmation uses the
   paired tool result; an edit request is not automatically a successful change.
3. Matches public test results to their calls and compares the **call's start index**
   with the last edit. A test started before an edit is not proof of the later state.
   The `run_tests` tool includes alternate public commands; `run_shell` is recognized
   as a test only for the task's exact reproduction command.
4. Prioritizes final submission, termination, final tests, recent edits and earlier
   context, retaining original event indices. It preserves the 100-event,
   16,000-character and 6,000-character-per-event bounds with explicit omission/truncation
   warnings. The original trace is never reordered or edited.
5. Projects controller-exported patch data into approved worker source files only.
   Raw diffs and all other patch fields are omitted; an unapproved file invalidates
   that export projection. This supplies final source already produced by the worker,
   not a reference solution.
6. Projects only the safe termination label from run-end context. It never forwards
   evaluator output, hidden-test names/results, raw run-end contents, full private task
   metadata, reference patches or private dependency explanations. Worker-like events
   after the first evaluator event are excluded.
7. Supplies deterministic execution facts: last edit, confirmed edit indices,
   submission indices, final visible-test state, evidence limits and policy version.
   Worker final messages, when enabled, are explicitly claims, not authoritative tests.
   The pilot's tools-only mode continues to omit model messages.

Zero-spend preflight on the actual two failed runs retained the complete final exports
first, with correct late-test states. It retained 30 events for task_101 (only the early
directory-call event 3 was truncated) and 28 for task_102 without warnings. Important
final source and late-test records were not truncated.

## Reflector output and validation changes

The [schema](/Users/arpitsrivastav/Desktop/swe_agent/src/reflexforge/meta/schemas.py) requires one attribution per run:

- `original_failure`: historical failure summary and appropriate evidence.
- `worker_changes`: actions and final source, distinguishing requests from confirmations.
- `final_observation`: what was actually observed after editing.
- `final_visible_test_state`: must equal the extractor's recorded state.
- `residual_status`: `supported` or `unknown`.
- `residual_cause`, `residual_evidence` and a mandatory uncertainty statement.

Unknown causes must use `residual_cause: null` and `residual_evidence: []`.
The Reflector must not infer the contents of withheld evaluator tests from a generic
failed outcome. Passing visible tests and no retest are both compatible with an unknown
residual cause. For these two historical runs, a supported residual diagnosis is rejected:
one final patch was not retested, and the other's final visible tests passed.

Each general diagnosis is scoped as `residual` or `process`. A residual attribution
requires a complete cited final-source record (or confirmed final edit) and a failing
visible test started after the last edit. Quotes must refer to actual source and test
output, not merely metadata keys. A residual diagnosis must include the attribution's
supporting evidence for every cited run. A grouped process diagnosis must cite action
or late execution evidence for every run; baseline assertions alone do not qualify.

Process diagnoses may describe an observable validation or execution gap while leaving
the residual cause unknown. They must not claim that the process gap is the hidden-test
failure's cause. If no grounded diagnosis is available, the output still records each
run's uncertainty and returns `diagnoses: []`. Existing optimizer/pilot control flow
then stops inconclusively instead of forcing a Proposer call or candidate evaluation.

The new [Reflector prompt and validator](/Users/arpitsrivastav/Desktop/swe_agent/src/reflexforge/meta/reflector.py) enforce
these distinctions. The [Proposer instructions](/Users/arpitsrivastav/Desktop/swe_agent/src/reflexforge/meta/proposer.py)
also preserve uncertainty and treat original failures as historical context.

Presence, stage and consistency validation are necessary safeguards, not a mathematical
proof that arbitrary natural-language causal explanations are true. A model could still
misinterpret the final code or overstate a process diagnosis; future human review must
assess that. The policy is deliberately conservative: static suspicion of a possible bug
does not establish why an unseen private evaluator rejected this particular patch.

All response fields remain required, nullable causes use an explicit string-or-null
schema, and extra object properties remain forbidden, consistent with the
[official Structured Outputs requirements](https://developers.openai.com/api/docs/guides/structured-outputs).

## Auditability and compatibility

New pilot plans, optimizer conditions and Reflector requests identify
`reflection_policy_version: 2`, `evidence_policy_version: 2`, and a SHA-256 of the
Reflector instructions. Bounded reflection-input files include the stage facts.

The worker model, worker prompt/workflow/skills, per-worker limits, tool permissions,
candidate allowlist, spending ledger and strict Gatekeeper were not changed. Existing
historical reflection JSON remains untouched and readable as audit data. Newly generated
reflection responses must satisfy the stricter schema; old unstructured diagnoses are
not silently grandfathered into a future proposal.

## Deterministic validation

[Regression tests](/Users/arpitsrivastav/Desktop/swe_agent/tests/test_reflector_attribution.py) use worker-only projections
of the real task_101/task_102 traces, with original event indices and original trace hashes.
Evaluator events/private payloads are removed from these checked-in fixtures, and
omitted rows preserve index positions. They contain no task-specific residual answer or
reference fix. No human baseline report is supplied to mocked or real meta inputs.

Tests cover:
- the exact old quote-attribution failure using schema-valid mocked responses;
- preserved final edits, late passing tests, missing retests and termination context;
- unknown/null residual causes and mandatory coverage of every run;
- phase/cross-run citation errors, metadata-only quotations and unsupported grouping;
- final-source truncation and large early transcripts;
- safe approved-source projection, evaluator/post-evaluator exclusion and source immutability;
- alternate public test commands and tests that started before the final edit;
- the strict response schema, mock Responses transport and the existing pilot/provenance flow.

These tests verify extraction, acceptance/rejection and data isolation. They do not
measure the live model's new diagnostic accuracy.

## Future real-pilot validation — not executed

After explicit paid authorization, reuse the same two verified training run IDs with
the existing bounded `meta-pilot` command. No training reruns are necessary. Inspect
preflight's new policy IDs and retained evidence before execution.

For the resulting audit, verify:
1. Both run attributions match the recorded final visible-test states and explicitly
   preserve uncertainty; neither claims an early failure proves the final patch's cause.
2. Any process diagnosis cites the appropriate action/late evidence and does not
   smuggle in a claimed private failure cause.
3. Any proposal follows only the validated diagnosis, not original-defect summaries,
   human reports, reference material or development feedback.
4. An evidence-insufficient/inconclusive result is accepted as correct behavior.
   Only evaluate an isolated candidate if a grounded proposal exists.

Do not send this human review document to the meta agent. An eventual candidate benefit
must still be measured on paired evaluations; improved schema compliance or a convincing
diagnosis is not evidence of worker self-improvement. No candidate is promoted by the
exploratory pilot.



## Verification recorded during implementation

- `.venv/bin/pytest tests/test_reflector_attribution.py tests/test_meta.py tests/test_meta_pilot.py -q -x`:
  **97 passed** (21 attribution cases plus 76 existing meta/provenance/pilot cases).
- `REFLEXFORGE_DOCKER_TESTS=1 .venv/bin/pytest -q`: **261 passed** in 51.88 seconds.
- `.venv/bin/ruff check src tests scripts`: passed.
- `.venv/bin/ruff format --check src tests scripts`: passed, 61 files formatted.
- Zero-spend preflight on both actual failed training runs: policy version 2, final exports
  retained, task_101 final test state `not_run`, task_102 final test state `passed`.
- **140 protected active-configuration/historical artifact files unchanged** after testing.
- No paid LLM calls, new candidate evaluation, or active worker configuration change.

See [Reflector diagnostic capture and literal citation matching](reflector-diagnostics.md)
for the follow-up audit fix: raw responses are preserved before parsing, rejected outputs
remain quarantined, and citations can match exact decoded supplied strings without fuzzy
matching. Historical v2 pilot records are unchanged.
