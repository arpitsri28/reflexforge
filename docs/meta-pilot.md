# First real RepoBench meta-optimization pilot

The pilot reuses verified real training failures, invokes the existing Reflector and
Proposer once each, validates one isolated configuration candidate, and compares it with
the incumbent on explicitly selected development tasks. It never promotes a candidate.
Implementation tests use mocked API responses and workers. No paid pilot has been run
as part of implementing this workflow; no improvement has been demonstrated.

## Preflight and explicit execution

Run from the repository root. The existing root `.env` supplies `OPENAI_API_KEY`.
Keep the worker model equal to the recorded baseline. Supply current USD-per-million
input/output rates for the chosen account/models; rates are required for both roles.
These interactive prompts use the default zsh shell:

```bash
source .venv/bin/activate
export OPENAI_MODEL=gpt-5.4-mini
export OPENAI_META_MODEL=gpt-5.4-mini
read 'REFLEXFORGE_INPUT_PRICE?Worker input USD per million tokens: '
read 'REFLEXFORGE_OUTPUT_PRICE?Worker output USD per million tokens: '
read 'REFLEXFORGE_META_INPUT_PRICE?Meta input USD per million tokens: '
read 'REFLEXFORGE_META_OUTPUT_PRICE?Meta output USD per million tokens: '
export REFLEXFORGE_INPUT_PRICE REFLEXFORGE_OUTPUT_PRICE
export REFLEXFORGE_META_INPUT_PRICE REFLEXFORGE_META_OUTPUT_PRICE
```

Zero-spend preflight is the default. It constructs neither API nor Docker clients and
does not create an optimization experiment or modify the source records:

```bash
reflexforge meta-pilot \
  --run-ids 2c1b9b2afdbf4039a7342df938ce154d,5563b7195e674d4f976e06f82442ec42 \
  --dev-tasks task_107 --max-api-calls 200 --max-tokens 200000 --max-usd 0.50
```

Alternatively select source experiments (the passed task_103 run is verified and recorded
as excluded from reflection):

```bash
reflexforge meta-pilot \
  --experiment-ids 2508458d048f41489d1cc51cb6fea948,9fd09c6ad0f14d74913bca37107588dd \
  --dev-tasks task_107 --max-api-calls 200 --max-tokens 200000 --max-usd 0.50
```

The following is the explicit **paid execution command**, provided for the user to run.
It rechecks provenance, makes at most two meta generations, then schedules one incumbent
and one candidate run on task_107. Start Docker and ensure that task's current bank/image
has valid QA (`reflexforge benchmark validate --suite repobench --tasks task_107` uses
Docker only). Preflight does not probe daemon connectivity or guarantee enough credits.

```bash
reflexforge meta-pilot \
  --run-ids 2c1b9b2afdbf4039a7342df938ce154d,5563b7195e674d4f976e06f82442ec42 \
  --dev-tasks task_107 --max-api-calls 200 --max-tokens 200000 --max-usd 0.50 \
  --execute
```

New pilot defaults are **200,000 global tokens, 200 API calls and $0.50**. All
three remain configurable through their CLI flags. Per-worker limits remain 24,000
tokens, 20 steps, 240 seconds, 30 seconds per command and 2,048 maximum response tokens.
The programmatic `BenchmarkSettings.run_budget` remains configurable, with the same
limits applied to incumbent and candidate and historical source compatibility enforced.

For one pair, full worker allocations total 48,000 tokens, leaving 152,000 global tokens
for meta work. At most 84 HTTP calls are scheduled across 20-step workers and two meta
generations/counts, below the 200-call ceiling. This removes the earlier observed global
token bottleneck for the same workload. The USD cap, per-worker caps and unknown-usage
protections still apply; preflight does not guarantee that arbitrary work will finish.

There are **zero training-worker reruns**. To compare more development tasks, explicitly
select e.g. `--dev-tasks task_107,task_108` and decide new overall caps after preflight.
Do not use held-out tasks. A comma-separated selection is frozen before proposing;
the meta agent cannot select evaluation tasks based on their outcomes.

## Admission and data isolation

Selectors accept explicit 32-character run IDs and/or experiment IDs, with duplicates
removed. An unknown selection, unfinished/synthetic source, or incompatible record is
rejected before constructing an API client. Explicit successful run IDs are rejected;
verified successes within selected experiments are audited and skipped. One to eight
failed training runs are required.

Admission checks the suite and training split, current content-addressed bank, manifest
task identity/source hash, source and execution configuration hashes, saved configuration
snapshot, model identifier, temperature, reasoning setting, execution budgets, real
provenance and completed/eligible cell status. It cross-checks the benchmark cell,
worker SQLite result, trace start/worker configuration and final result. Paths must remain
inside the recorded experiment store. Symlink escapes, inconsistent records and oversized
traces are rejected. Original databases are opened read-only. Raw trace and result hashes
are retained in the new audit; source traces are never rewritten.

This establishes local record consistency, not cryptographic authenticity against an
attacker who can rewrite all source databases and traces. Matching model identifiers
also do not prove a provider alias will forever resolve to the same model snapshot.

Reflection retains only worker-visible tool calls/results and API error/retry events.
Evaluator events, run-start private task metadata, final evaluation results and raw patch
events are excluded. Approved worker-source exports are now projected separately as
final-submission evidence, alongside safe termination metadata. Model responses are omitted in this reuse mode to avoid duplicating
tool arguments within the existing 16,000-character/100-event evidence bounds. Individual
events are bounded to 6,000 characters; explicit truncation warnings and retained event
counts are shown in preflight and audit. Evidence indices use the existing zero-based
trace line index (physical JSONL line = index + 1).

The Reflector receives that bounded evidence, generic termination/category labels and
the incumbent configuration. Its exact quotations are validated by the existing evidence
checker. The Proposer receives only that reflection, the configuration and an empty
rejection history. The human baseline analysis, private tests, references, dependency
explanations and development outcomes are never supplied. Selected development task IDs
stay in controller audit metadata, outside meta prompts. Development fixtures are loaded
for execution only after the proposal is fixed. All task code still executes through the
existing sandbox and independent evaluator.

The unchanged structured-call implementation uses Responses JSON Schema output and
Pydantic validation. See the [official OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Candidate, paired comparison and budget

The incumbent is copied into a dedicated pilot directory. The existing candidate allowlist
permits one prompt/workflow/skill file replacement, rejects parameter/tool changes, and
requires a real configuration change. Valid candidates are retained under their content
hash; they are never written to the active configuration or accepted Git store. Invalid
proposals remain in the audit without evaluation. Insufficient reflection evidence stops
with an inconclusive result and no proposal or worker runs.

The existing benchmark runner evaluates `static` and `candidate` with identical model,
sampling, tools and per-run limits: 20 steps, 24,000 tokens, 2,048 maximum response tokens,
240 seconds, 30 seconds per command and zero request retries. It freezes configurations
and task snapshots, alternates condition order using its seeded shuffle, and preserves
per-cell provenance and independent evaluator outcomes. The source training settings
must match these settings; incompatible historical runs are rejected rather than silently
mixed.

**One durable ledger covers both meta generations, input counting, and every worker
condition.** The benchmark runner does not reset the pilot's caps after proposing.
USD enforcement requires explicit worker and meta prices. Input/output reservations,
unknown-usage blocking and disabled SDK retries remain in effect. Preflight's worker-only
bound is labeled separately from overall caps; meta input is counted at runtime. Caps
may stop before a proposal, a complete pair, or any worker completion. Historical training
costs are not charged again or counted as newly spent pilot tokens.

Interrupted work is persisted, including partial benchmark cells where created. A later
invocation marks stale work interrupted/uncertain and starts a **new**, explicitly budgeted
pilot. It never automatically resumes or retries paid requests. Inspect unresolved spend
before deciding to authorize another invocation.

The existing exploratory comparison reports paired wins/losses, omitted pairs, tokens,
runtime, tool calls and cost estimates. It always records `promotion: false`. Benchmark
reports follow the shared pilot ledger and label aggregate API accounting as meta plus
development worker usage. The strict Gatekeeper is unchanged and is not invoked by the
pilot. Four distinct development tasks cannot satisfy its five-improved-task requirement;
repetitions cannot fix that. One pair provides especially limited evidence. A candidate
benefit, if any, must be measured rather than inferred from the proposal or mock tests.

## Audit locations

The command returns the new pilot ID, status, usage and absolute audit path:

- `artifacts/optimization/repobench/pilots/real/PILOT_ID/plan.json`: frozen selections,
  source trace/result hashes, model/config versions, budgets and preflight bounds.
- `reflection-input.json`: exact retained training evidence; the accompanying incumbent
  snapshot is the remaining Reflector input.
- `audit.json`: reflection, proposal (including invalid proposals), candidate hash/path,
  benchmark ID, full paired cell outcomes, exploratory comparison, usage and errors/status.
- `incumbent/` and `candidates/CONFIG_HASH/config/`: isolated reproducible configurations.
- `artifacts/optimization/repobench/pilots/real/optimization.sqlite3`: pilot status and
  shared API reservation/usage ledger. Unknown or interrupted spend remains auditable.
- `artifacts/benchmark/repobench/real/experiments/BENCHMARK_ID/`: normal paired benchmark
  conditions, worker traces, patches, evaluator results and SQLite cells, with a link to
  the shared pilot budget ID.

Mock executions use separate `synthetic` pilot and benchmark stores and are never evidence
of actual model improvement. Real proposal/evaluation records will exist only after the
explicit paid command is executed. No placeholder real outcomes are fabricated.

```bash
reflexforge benchmark compare BENCHMARK_ID --suite repobench
reflexforge benchmark report --experiment BENCHMARK_ID --suite repobench
```

The pilot does not feed evaluator-informed audit reports back into Reflector/Proposer.
Review them as human research artifacts, separate from permitted training evidence.

## Verification

The unit tests create disposable real-shaped admission records and use mocked Responses
and workers; they do not depend on ignored historical run artifacts being checked out.
They cover provenance mismatches, source immutability, forbidden-material access,
candidate isolation, one-proposal behavior, shared request/token/USD caps, partial cells
and interruption audit. All live HTTP remains forbidden by the test-suite fixture.

Run:

```bash
.venv/bin/pytest tests/test_meta_pilot.py -q
REFLEXFORGE_DOCKER_TESTS=1 .venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
```

Verification recorded during implementation:

- `.venv/bin/pytest tests/test_meta_pilot.py -q -x`: **24 passed**.
- `REFLEXFORGE_DOCKER_TESTS=1 .venv/bin/pytest -q`: **222 passed** (54.17 seconds).
- `.venv/bin/ruff check src tests scripts`: passed.
- `.venv/bin/ruff format --check src tests scripts`: passed, 57 files formatted.
- Real-record preflight using both source experiment IDs admitted task_101/task_102,
  verified and excluded task_103, retained 28/26 worker events without truncation,
  and reported zero training reruns and no paid requests. Both explicit-run selection
  and experiment selection were exercised without constructing API/Docker clients.
- No real Reflector, Proposer, candidate worker, or new benchmark evaluation was launched.
  Live pilot behavior and any empirical benefit remain unverified.


## Offline completion of interrupted submissions

The first pilot's incumbent was reconstructed from a confirmed source-edit event and
independently evaluated without an LLM call. It passed 6/6 checks, matching the candidate;
the original pilot remains budget-exhausted and its paired result remains incomplete.
See [post-hoc recovery and resource adjustment](meta-pilot-posthoc.md).

The reusable offline command is:

```bash
reflexforge benchmark posthoc-evaluate \
  04f46d7a076d4971a9742527625d015f 4b7ab881deaa4131a147e5c819ce4847
```

It writes a separate post-hoc artifact, not a replacement experiment cell. Only confirmed,
approved `edit_file` replacements are replayed. Arbitrary shell commands, nonstandard
test commands, ambiguous edits, hash mismatches and already-evaluated runs are rejected.
This reconstruction assumes tests/setup did not perform unlogged source writes; it does
not assert byte-for-byte recovery of a destroyed workspace. Future global budget stops
are recorded as `budget_exhausted`, not generic controller or coding failures. Historical
records are not relabeled.

See [Reflector attribution policy version 2](reflector-attribution.md) for stage-aware
evidence selection, required per-run uncertainty, and rejection of early failures as
proof of final residual defects. Historical pilot audits remain unchanged.

Reflector generations now create private, immutable diagnostic artifacts before parsing
or citation checks. See [diagnostic lifecycle and safe offline inspection](reflector-diagnostics.md).
Rejected outputs cannot reach the Proposer; they remain available for human review.
