# Milestone 2: autonomous configuration optimization

This checkpoint originally used three fixtures and one dev task. Milestone 3 now supplies
38 fixtures and 12 dev tasks; see [the current guide](milestone-3.md). The strict gate
is unchanged. References below to the single-task bank describe the original M2 checkpoint.

The implementation adds a real OpenAI-backed reflector and proposer, isolated configuration
candidates, deterministic paired evaluation, Git versioning, and a bounded outer loop.
It does not modify model weights, worker tools, task fixtures, sandbox controls, or scoring.
No live optimization experiment was run during implementation. Synthetic demonstrations
exercise control flow; they provide no evidence of improved coding performance.

## Architecture

The existing `run_worker` remains the worker/evaluator entry point. Its only new argument
is an optional pinned model. The optimizer passes an `AgentConfig` loaded from an immutable
snapshot, a shared budgeted API client, and a Docker factory using a captured image ID.
The worker agent, sandbox, and independent evaluator keep their existing implementations.

New modules:

| Module | Responsibility |
| --- | --- |
| `meta/schemas.py` | Strict diagnosis, evidence, proposal, and optimization settings |
| `meta/reflector.py` | Bounded training evidence selection and citation verification |
| `meta/proposer.py` | One file replacement expressing one conceptual improvement |
| `meta/llm.py` | OpenAI Responses structured JSON output with Pydantic validation |
| `meta/versioning.py` | Candidate validation, complete snapshots, Git commits, active pointer, rollback |
| `meta/budget.py` | Shared, durable API call/token/USD reservations |
| `meta/state.py` | SQLite experiment/iteration/usage state, JSONL audit, locking, recovery |
| `meta/optimizer.py` | Explicit training → reflection → proposal → dev comparison → publication loop |
| `meta/demo.py` | Explicit synthetic Responses and worker fixtures for demonstrations |
| `evaluation/gatekeeper.py` | Deterministic comparisons, uncertainty and resource regression checks |

OpenAI requests use strict `text.format` JSON schemas, validated again using Pydantic.
See [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
The meta model defaults to the worker model and can be independently set using
`OPENAI_META_MODEL`. Worker model selection stays fixed throughout an experiment.

## Data boundaries

Only train and dev manifests are loaded by optimization; test manifests are not parsed.
Their fixtures and hidden tests are copied into an experiment-local frozen task bank.
Conditions record settings, a task-content fingerprint, and the Docker image ID. Each
worker execution still gets its own clean container and independent evaluator container.
Results are not cached or reused between incumbent and candidate.

Reflection receives failed, independently evaluated **training** runs only. Allowed input
includes worker-visible tool calls/results, model outputs, API error types, termination,
configuration version, and current worker configuration. Evaluator output, hidden tests,
patch/evaluation events, and dev/test traces are excluded. Malformed/mismatched events
are skipped with warnings; missing or oversized traces cannot support a proposal.
At most eight traces, 100 events and 16,000 retained characters per trace are supplied.
Individual events are capped at 6,000 characters and marked when truncated.

Each evidence item names a run, original event index, and exact quotation. References
and quotes must actually occur in the supplied retained events. This validates citations;
it cannot prove that the LLM's causal explanation is correct. Diagnoses and hypotheses
remain research hypotheses. Multiple failures can be grouped into recurring diagnoses.

The proposer receives training diagnoses and current configuration. Rejection feedback
contains only earlier hypotheses and outcome labels, with no dev-task identifiers,
patches, evaluation output, metrics, or gatekeeper reasons.

If all training tasks pass, the iteration records `no_failures` and stops before either
meta request or dev evaluation. Successful runs are never relabeled as failures. If
failure traces are unusable, or diagnoses lack evidence, it records an inconclusive
outcome. The existing three real fixtures are unchanged; no artificial failures or new
research tasks were added just to force a live optimization example.

## Configuration safety and versioning

Candidates permit exactly one target:

- `config/system_prompt.md` with `modify_prompt`;
- `config/workflow.yaml` with `modify_workflow`;
- `config/skills/NAME.md` with `upsert_skill`.

Names, file sizes, configuration schema, file types, and symlink-free paths are checked.
Traversal, absolute paths, nested skill paths, parameter/tool edits, unknown files,
invalid workflows and no-op changes are rejected. Tools and execution parameters must
remain identical. The one-concept constraint is instructed in the proposal prompt;
validation mechanically enforces one file replacement, not semantic proof of one idea.

State lives under `artifacts/optimization/real/`. Synthetic runs use a completely separate
`artifacts/optimization/synthetic/` store. Each contains:

- `config-git/`: a dedicated Git repository with complete accepted snapshots and metadata;
- `active.json`: an atomically replaced content-hash pointer;
- `candidates/`: isolated proposed snapshots, retained for audit even when rejected;
- `optimization.sqlite3`: experiment, iteration, and API usage records;
- `audit.jsonl`: redacted history;
- `experiments/ID/`: frozen task inputs, conditions, and worker traces/databases.

The first baseline and each new accepted snapshot receive a Git commit. Version IDs are
SHA-256 hashes of the complete parsed configuration. Metadata records the parent version,
proposal, training evidence, evaluation decision and iteration ID. Rejected proposals
never publish an active pointer or receive an accepted-version commit. Git commands run
only in this dedicated repository, with inherited Git directory/index overrides and
external hooks disabled. The developer's source `config/` and project index are untouched.

`run-worker`, `evaluate`, and `doctor` default to the active real snapshot when one exists.
An explicit `--config config` on worker/evaluate selects the source configuration instead.
A synthetic accepted version never becomes the real worker's default.

```bash
reflexforge config-history
reflexforge proposals
reflexforge show-iteration ITERATION_ID
reflexforge rollback-config ACCEPTED_VERSION
```

Rollback switches the atomic pointer to a validated, previously committed snapshot and
records an audit event. It does not rewrite Git history or experiment results. Add
`--synthetic` to inspect or roll back demonstration history.

## Gatekeeper policy

Incumbent and candidate run on exactly the same frozen dev tasks, with the same number
of attempts, model, image, tools, execution limits, and independent evaluation rules.
The order alternates deterministically across tasks and repetitions. Only evaluator
exit status determines success; no LLM grades patches.

The gate rejects missing/duplicate comparisons, model/version/provenance mismatches,
unknown API usage, infrastructure/controller failures, any paired success regression,
or excessive aggregate token/time/tool/cost consumption. The default resource ceiling
is 1.25 times incumbent consumption. Missing dollar estimates remain missing, not zero.

Ties or small apparent improvements are inconclusive. Acceptance requires at least five
improved task IDs, no negative paired outcomes, and a one-sided task-level sign-test
probability at most `0.05 / max_iterations`. Repetitions of a task do not count as
independent tasks. The audit reports the exact probability and paired outcomes. This
is conservative screening, not proof of generalization; task correlations, model
nondeterminism, repeated dev-set adaptation, and noisy wall times remain limitations.

**The current single dev task cannot establish acceptance under this policy**, regardless
of repetitions. Extend and freeze a diverse dev bank before interpreting real optimization
as evidence. Held-out test comparisons and full baseline research reporting remain later
milestone work. No final test tasks are used to tune this policy during optimization.

## Cost limits and interruption recovery

Every OpenAI HTTP operation is accounted for, including input-token counting. Both worker
and meta generations reserve the full counted input plus maximum possible output before
sending the request. Call and token limits are shared across all stages and iterations.
Actual usage replaces the reservation after a response; cached input is conservatively
priced as ordinary input for USD-cap purposes. Reasoning tokens are already in output.
Requests use the standard service tier with storage disabled.

A USD cap requires explicit nonnegative, finite input/output rates for **both** models.
It fails before any API call if those rates are absent. Pricing is supplied by the user,
not inferred from the model name. It must match the actual standard text-token billing
and account context; incorrect pricing or provider-side changes cannot be guaranteed
against. No model pricing is hardcoded. Regional/tax/other non-token charges are outside
this estimator. `usd_upper_bound: null` means unpriced, never free.

A lost response, server error, interrupted generation, or missing usage retains its full
reservation and blocks further API requests for that experiment. Overruns are recorded
and halt execution. SDK retries are disabled. Budget reservations are SQLite transactions,
so a crash cannot erase an in-flight request's reservation.

A nonblocking filesystem lock prevents concurrent optimization/rollback writers. Pointer
publication follows the Git commit. On the next invocation, stale running iterations
become interrupted; an already-published accepted decision is reconciled as accepted.
Pending usage becomes unknown. Local Git publication can recover without replaying model
requests. Interrupted paid iterations are **not automatically rerun**: a new invocation
starts a new explicitly budgeted experiment from the last published accepted version.
Caps apply per experiment, not across separately requested invocations. This recovery
strategy favors avoiding duplicate spend over transparent in-place resumption.

POSIX file locking is required (macOS/Linux). Docker hard-crash/orphan-container recovery
remains subject to the existing Milestone 1 limitations in [security.md](security.md).

## Zero-spend demonstration

These commands do not construct a live OpenAI or Docker client:

```bash
.venv/bin/reflexforge optimize --dry-run --iterations 1 --scenario accept
.venv/bin/reflexforge optimize --dry-run --iterations 1 --scenario reject
.venv/bin/reflexforge optimize --dry-run --iterations 1 --scenario no-failures
.venv/bin/reflexforge config-history --synthetic
.venv/bin/reflexforge proposals --synthetic
# Use an iteration ID printed by optimize:
.venv/bin/reflexforge show-iteration ITERATION_ID --synthetic
```

Acceptance/rejection demos contain an explicitly mocked training failure and five scripted
synthetic dev comparisons. The latter exercise the conservative gate; they are not five
new independent research fixtures. All run and experiment records are marked synthetic,
live and synthetic active pointers are separate, and normal real-run metrics exclude
synthetic worker rows. Synthetic API-call/token counts describe mocked activity and
must never be reported as actual spend or benchmark performance.

During implementation, acceptance, rejection and no-failure scenarios all completed.
The acceptance demo recorded a Git version; rejection/no-failure preserved the incumbent.

## One controlled real iteration (commands only; not executed)

After explicit approval to spend API credits, use your existing repository-root `.env`
key and a running Docker daemon with the sandbox image available. For these two identical
models, the official standard text rates verified on November 7, 2026 were $0.75 input
and $4.50 output per million tokens; verify current rates before spending.
[Model and pricing reference](https://developers.openai.com/api/docs/models/gpt-5.4-mini).

```bash
source .venv/bin/activate
export OPENAI_MODEL=gpt-5.4-mini
export OPENAI_META_MODEL=gpt-5.4-mini
export REFLEXFORGE_INPUT_PRICE=0.75
export REFLEXFORGE_OUTPUT_PRICE=4.50
export REFLEXFORGE_META_INPUT_PRICE=0.75
export REFLEXFORGE_META_OUTPUT_PRICE=4.50
reflexforge doctor
reflexforge optimize --iterations 1 --repetitions 1 \
  --max-api-calls 40 --max-tokens 30000 --max-usd 0.25
```

The call limit includes counting requests. Conservative reservations may stop a run before
all stages fit in the budget. If training passes, the loop stops normally with no proposal.
A genuine failure is required for reflection; the current dev bank cannot justify real
acceptance. Live reflector/proposer generation and actual optimization gains remain
unverified. The existing Docker fixture tests and mocked integration tests verify the
implementation, not improvement on unseen coding tasks.

## Validation record

The unit/mock suite passed 105 tests (five Docker tests skipped in the default run).
The separately enabled Docker suite passed all five existing tests. A later combined
suite run had 109 passes and one Docker daemon container-create timeout; the affected
test passed its targeted rerun. The final complete run then passed **110 tests, with zero
failures and zero skipped**, with Docker enabled. Lint, formatting and `pip check` passed.
Live LLM calls were never enabled.
