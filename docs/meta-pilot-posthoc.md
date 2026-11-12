# Pilot resource limits and post-hoc incumbent evaluation

The incumbent's recorded `cache.py` edit was recovered and passed **6/6 independent
checks**, matching the candidate's original **6/6 pass** on task_107. There is no
observed task-success advantage for the candidate. The original paired pilot remains
budget-exhausted and incomplete; this separate post-hoc check does not relabel it.

No new paid API call, worker generation, Reflector call or Proposer call was made.

## Recovery and independent evaluation

Original pilot: `06b8bd436b134c6281be7ea2bd7f4e02`.
Original benchmark: `04f46d7a076d4971a9742527625d015f`.
Incumbent run: `4b7ab881deaa4131a147e5c819ce4847`.
Separate post-hoc evaluation: `abd003db9bfa449aa58dde17f556a1be`.

The original worker workspace was destroyed during exception cleanup, and its final
patch snapshot was not exported. However, its complete replacement of `cache.py`
is present in the successful [tool call at trace line 40](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/real/experiments/04f46d7a076d4971a9742527625d015f/runs/traces/4b7ab881deaa4131a147e5c819ce4847.jsonl:40)
and [confirmation at line 41](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/real/experiments/04f46d7a076d4971a9742527625d015f/runs/traces/4b7ab881deaa4131a147e5c819ce4847.jsonl:41).
There were no arbitrary shell commands or other source edits in that trace. Its
[final visible tests passed at line 44](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/real/experiments/04f46d7a076d4971a9742527625d015f/runs/traces/4b7ab881deaa4131a147e5c819ce4847.jsonl:44).

The recovered one-line substantive change was:

```diff
-        return (document.key, action)
+        return (principal.key, principal.revision, document.key, document.revision, action)
```

The new recovery command verified the original conditions hash, real provenance,
read-only database records, frozen configuration, task/hidden-test content hash,
manifest version and trace/result consistency. It replayed only confirmed allowlisted
file replacements into the original source snapshot. It passed that patch to the
existing independent Evaluator in a fresh Docker container using the original image:

`sha256:a652ee72cbe2908d0649a0fad5063611255481a74a2a8130a515bd2574ff25b3`.

The original frozen hidden tests returned exit 0, six tests run, no failures or errors.
No hidden tests, fixtures or reference solutions were changed. The original evaluator
implementation was reused without modification.

Artifacts:

- [Post-hoc provenance and authoritative evaluation output](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/posthoc/real/abd003db9bfa449aa58dde17f556a1be/recovery.json)
- [Recovered unified diff](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/posthoc/real/abd003db9bfa449aa58dde17f556a1be/patch.diff)
- [Recovered source overlay](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/posthoc/real/abd003db9bfa449aa58dde17f556a1be/patch.json)
- [Original immutable pilot audit](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/optimization/repobench/pilots/real/06b8bd436b134c6281be7ea2bd7f4e02/audit.json)
- [Original candidate evaluator event](/Users/arpitsrivastav/Desktop/swe_agent/artifacts/benchmark/repobench/real/experiments/04f46d7a076d4971a9742527625d015f/runs/traces/82d67b5a6686470abab627fcb803c361.jsonl:47)

The offline command executed was:

```bash
.venv/bin/reflexforge benchmark posthoc-evaluate \
  04f46d7a076d4971a9742527625d015f 4b7ab881deaa4131a147e5c819ce4847
```

It writes a new post-hoc artifact, not an experiment cell or a replacement audit.
Do not rerun it merely to complete the original pair: the needed offline check is done.

## Comparison and provenance limits

| Condition | Evidence | Independent result |
|---|---|---|
| Candidate | Original real run `82d67b5a6686470abab627fcb803c361` | 6/6 passed |
| Incumbent | Reconstructed patch from original real run `4b7ab881deaa4131a147e5c819ce4847`; evaluated afterward | 6/6 passed |

The outcome is a post-hoc success tie on the existing task_107 checks, not a completed
prospective pair or proof of equivalent general coding ability. The two patches use the
same substantive key expression. The original static benchmark cell remains
`budget_exhausted` with null result. Its original worker trace still says
`controller_error` and `evaluation: not_run`, reflecting the historical wrapper's
handling of `BudgetExceeded`. None of those records were rewritten.

Recovery is from recorded edit arguments, not a byte-for-byte final workspace capture.
It assumes tests/setup made no unlogged source writes. The reconstructed approved patch,
rather than any discarded runtime state, is what the fresh independent evaluator checked.
No additional LLM completion or revised repair was supplied.

Fingerprints covering 209 original audit, database, trace, frozen task/configuration,
benchmark fixture and active-configuration files were captured before offline evaluation.
They remained identical afterward. The post-hoc record also stores its own source
fingerprints and `source_records_unchanged: true`. Active pointers and the strict
Gatekeeper are unchanged; no candidate was promoted. Original API usage and cost records
also remain unchanged. Budget exhaustion is not counted as a coding failure.

## Resource changes for the next authorized pilot

| Limit | Prior pilot | New default |
|---|---:|---:|
| Global combined tokens | 60,000 | **200,000** |
| Global HTTP calls, including counting | 84 | **200** |
| Global USD cap | $0.30 | **$0.50** |
| Per-worker combined tokens | 24,000 | 24,000 |
| Per-worker generation steps | 20 | 20 |
| Worker / command timeouts | 240 s / 30 s | 240 s / 30 s |
| Maximum response tokens / request retries | 2,048 / 0 | 2,048 / 0 |

Global limits remain CLI-configurable; the shared ledger still reserves input plus
maximum output, enforces token/call/USD caps, blocks uncertain usage and prevents
automatic replay. Per-worker budgets remain configurable through the existing
`BenchmarkSettings.run_budget` and are normalized identically for both conditions.
The active worker's configuration files were not edited to change experimental limits.

One full worker pair allocates at most 48,000 tokens and 80 HTTP calls; the two meta
generations/counts add at most four HTTP calls. New preflight reports 152,000 tokens
of meta headroom after full worker allocations and an 84-call schedule below the
200-call cap. This comfortably covers the observed 13,419-token meta workload and
both full worker allocations. It does not guarantee arbitrary future meta input fits
or that the USD cap can never stop execution. At configured rates, the deliberately
conservative all-tokens-at-maximum-rate bound can exceed $0.50; the hard spending cap
still takes precedence.

Future propagated global budget exceptions now record `budget_exhausted` /
`execution_budget_exhausted` with evaluation `not_run`, rather than a generic
controller failure. They remain unevaluated, not coding failures. This change applies
only to future runs, not the preserved historical pilot.

## Commands for a new real experiment — not executed

Use the existing key, model and configured worker/meta prices. A new pilot is not needed
to recover the missing result above; these commands are for a future authorized iteration.

Preflight (no API client or paid calls):

```bash
.venv/bin/reflexforge meta-pilot \
  --run-ids 2c1b9b2afdbf4039a7342df938ce154d,5563b7195e674d4f976e06f82442ec42 \
  --dev-tasks task_107 \
  --max-tokens 200000 --max-api-calls 200 --max-usd 0.50
```

Explicit paid execution, only when authorized:

```bash
.venv/bin/reflexforge meta-pilot \
  --run-ids 2c1b9b2afdbf4039a7342df938ce154d,5563b7195e674d4f976e06f82442ec42 \
  --dev-tasks task_107 \
  --max-tokens 200000 --max-api-calls 200 --max-usd 0.50 \
  --execute
```

The paid command starts one new Reflector/Proposer iteration and a new prospective pair;
it does not resume or overwrite the original pilot. No such command was run during this
resource adjustment. To test the already-created candidate on a new selected development
task instead, the existing benchmark `candidate` condition can reuse its frozen path
without invoking Reflector/Proposer; choose that follow-up explicitly rather than
regenerating a candidate solely to recover an old result.



## Verification results

- `.venv/bin/pytest tests/test_posthoc.py tests/test_meta_pilot.py tests/test_orchestrator.py -q -x`:
  **50 passed** before adding the Docker-only recovery integration case.
- `REFLEXFORGE_DOCKER_TESTS=1 .venv/bin/pytest -q`: **240 passed** in 56.32 seconds,
  including the new end-to-end recovery/evaluator Docker test and existing integrations.
- `.venv/bin/ruff check src tests scripts`: passed.
- `.venv/bin/ruff format --check src tests scripts`: passed, 59 files formatted.
- Increased-budget preflight: 200,000 tokens / 200 calls / $0.50; identical unchanged
  worker limits; 152,000 tokens of meta headroom; no paid calls.
- Protected original-file fingerprint check after all tests: **209/209 unchanged**.

Tests use mocks or offline Docker execution, never paid LLM HTTP. No new real meta-pilot
or paid worker condition was started during this adjustment.
