# Milestone 3: controlled debugging-agent experiments

Implementation status: a 38-task benchmark, Docker fixture QA, paired baseline runner,
reflection-only condition, accepted-meta configuration evaluation, exploratory analysis,
budget preflight, and Markdown/Matplotlib reporting are implemented. No live baseline or
meta-optimization experiment was run during implementation. There is no evidence yet
that configuration optimization improves coding ability.

## Benchmark and provenance

The bank contains **18 training, 12 development, and 8 test tasks**. All are project-authored
synthetic debugging fixtures, not real GitHub issues or SWE-bench tasks. Static labels are
**3 easy, 20 medium, and 15 hard**. These are authoring categories; empirical difficulty
must be established through actual agent results. Most fixtures have two cooperating
modules; two reference fixes require changes in two modules. Small repositories and
clear bug reports are intentional, and may still be easy for capable models.

The original three fixtures are preserved. All three were previously exercised by the
worker, including legacy test task `task_003`. Consequently **seven test tasks are fresh**;
the full eight-task test set must not be described as historically untouched. The manifest
records `prior_agent_exposure`; reports distinguish fresh-only test comparisons. No test
fixture is loaded by the optimizer, and no held-out agent evaluation was run in this work.

The task families cover state, caches, async behavior, concurrency, retries, configuration,
serialization, authorization/authentication, imports, pipelines, lifecycle cleanup,
pagination, validation, ordering, datetime handling, parsing, routing, binary protocols,
interval algorithms, event dispatch, weighted analytics, and URL encoding. Related broad
exception-handling and context-resource-cleanup families are kept in training. Family
cross-split checks and normalized-AST near-duplicate screening run before fixture QA.
This heuristic is not a semantic plagiarism detector; human review remains appropriate.

See [benchmark inventory](benchmark-inventory.md) for the exact category distribution,
per-task coverage, affected-module counts, and validation status.

### Layout and versioning

- `tasks/SPLIT/ID/task.json`: existing runtime schema, issue, reproduction, budgets, editable files.
- `tasks/SPLIT/ID/repo/`: worker-visible source and reproduction checks only.
- `tasks/SPLIT/ID/hidden.py`: independent controller-owned regression checks.
- `benchmark/references/ID.json`: private known-correct source overlays, never worker uploads.
- `benchmark/manifest.json`: private difficulty/family/coverage metadata and content hashes.
- `benchmark/validation.json`: recorded real Docker fixture QA, not agent benchmark scores.
- `scripts/benchmark_catalog.py`, `scripts/build_benchmark.py`: trusted authoring data and materialization.

The manifest version is a SHA-256 hash of canonical metadata, including fixture and
reference hashes. Fixture hashes cover the raw manifest, repository contents and hidden
tests. Reference overlays have separate hashes and must change approved existing source
files only. Workers receive none of the private metadata or reference overlays.

### Fixture QA

Every fixture was validated in Docker: its original visible reproduction and regression
checks fail; its reference visible reproduction and full hidden checks pass. Both buggy
and reference hidden checks run twice with equal output/status. Original and reference
runs use separate pristine containers. Fixtures are never imported or executed on the host.

QA records include exact source/reference hashes, immutable Docker image ID, exit codes,
and output. A passing pytest process alone does not validate a fixture: the tests assert
that the original fails and the reference passes. Recorded QA is tied to the fixture
hashes; live benchmark runs require matching QA and the same image ID. A changed image
requires revalidation. Two repetitions and deterministic event-based async reproducers
reduce nondeterminism; they are not proof that all possible schedules are equivalent.

```bash
source .venv/bin/activate
reflexforge benchmark list
reflexforge benchmark validate --structure-only
reflexforge benchmark validate --workers 2
# Revalidate a subset when developing fixtures:
reflexforge benchmark validate --tasks task_019,task_020 --workers 2
```

`validate` runs code exclusively in Docker and does not call an LLM. Authoring script
execution materializes source strings as files; it never executes those strings on the host.

## Evaluation runner and conditions

New modules under `src/reflexforge/benchmark/` implement manifest validation, fixture QA,
settings/preflight, durable cell state, the runner, clustered statistics, and the CLI.
`analysis/reports.py` creates standalone PNG charts, JSON summaries, and Markdown reports.
The existing sandbox and evaluator are unchanged. Worker integration adds optional
reflection-only feedback and explicit sampling arguments; ordinary worker behavior is
unchanged when these options are absent.

Each experiment freezes selected fixtures and configuration files, records bank/version
hashes, model, image ID, sampling, task subsets, attempt counts, and resource limits, then
schedules paired `(task, attempt, condition)` cells. Conditions execute in seeded shuffled
order. Each execution still uses its own Docker workspace and independent hidden evaluator.
There is no billable result cache or automatic replay of incomplete requests.

### A: static

Uses the source `config/` by default, even if a globally optimized active pointer exists.
This prevents the baseline from silently becoming the optimized configuration. `--config`
can explicitly select another fixed configuration directory.

### B: within-task reflection

Uses the same prompt/configuration as static. After the model first declares completion,
the controller runs the visible reproduction. If it fails and budget remains, the worker
gets one explicit reflection/retry opportunity in the same workspace. Only visible stdout,
stderr and exit status are fed back. Hidden evaluation occurs afterward and is never
shown to this worker. Reflection calls, tokens, command time and tool count consume the
same per-run budgets as static; a `reflection_retries` counter records the extra attempt.

This is an explicit additional feedback policy, not a separate persisted configuration.
The normal static tool loop already allows self-correction; that behavior remains intact.

### C: meta-optimized

Requires `--optimized-version` referring to an actual accepted configuration in the **real**
Milestone 2 Git store. A synthetic acceptance or baseline-only snapshot is rejected.
The accepted metadata must match the worker model and benchmark version. Old unversioned
accepted configurations must be reevaluated under this bank before use. Snapshot prompts,
workflow and skills are used without modifying the source configuration.

### Fairness and limits

All compared conditions use identical tools and a common execution budget: default
8 generation steps, 8,000 combined input/output tokens, 1,024 output tokens per turn,
120 worker seconds, 20 command seconds, zero request retries, and the existing tool-call
ceiling. A/B use the same execution configuration hash. C may differ in approved behavior
files, with execution parameters rewritten identically in its isolated benchmark snapshot.
Both source and execution hashes are recorded to make this distinction explicit.

Benchmark sampling is fixed at temperature 0 and reasoning effort `none` for the default
`gpt-5.4-mini` model; optimization with this versioned bank uses the same settings.
[Official parameter guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.4)
and [model support](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
Other models need compatible settings; programmatic settings allow omitted temperature
and reasoning parameters. Low temperature does not guarantee deterministic API outputs.
Use an available immutable model snapshot for a frozen research study.

Every generation shares the Milestone 2 durable request/token/USD ledger. Reservations
include counted input plus maximum output. Reflection and repeated attempts cannot bypass
the ledger. Baseline runs require only worker pricing for a USD cap; optimization requires
worker **and** meta pricing. Missing price estimates never become zero. Unknown usage
blocks further requests. Standard-tier token prices are supplied explicitly and must
reflect the chosen models/account; non-token surcharges are outside the estimator.

Infrastructure/API/setup failures are labeled separately from independently evaluated
coding failures. Missing, interrupted, budget-exhausted or infrastructure-only outcomes
are not silently converted to failed coding attempts. Partial reports retain scheduled,
completed, coding-eligible and unevaluated counts, with experiment-wide accounting including
unresolved reservations. A new invocation marks stale cells interrupted and starts a new
explicitly budgeted experiment; it does not automatically rerun paid work.

## Preflight and zero-spend planning

```bash
reflexforge benchmark preflight --split train --tasks task_001 \
  --conditions static,reflection --attempts 1 \
  --max-api-calls 32 --max-tokens 16000
reflexforge benchmark run --split train --tasks task_001 \
  --conditions static,reflection --dry-run
```

Preflight returns potential generation/HTTP request maxima, token reservations, optional
USD bounds, and cap settings. These are planning bounds, not measured usage. Caps may
prevent all scheduled cells from completing. `--dry-run` records a **synthetic plan with
pending outcomes**; it creates no OpenAI or Docker clients and invents no coding scores.
Synthetic experiment files and real experiment files have separate stores. Unit tests
block all live httpx transports; SDK protocol tests must explicitly use MockTransport.

## Controlled real commands — not executed during implementation

Use the existing repository-root `.env` key, a running Docker daemon, and validated fixtures.
The examples below use standard `gpt-5.4-mini` rates documented on November 8, 2026; verify
rates and model availability before authorizing a run. Changing model/image/bank versions
requires appropriate matching validation and study metadata.

```bash
source .venv/bin/activate
export OPENAI_MODEL=gpt-5.4-mini
export OPENAI_META_MODEL=gpt-5.4-mini
export REFLEXFORGE_INPUT_PRICE=0.75
export REFLEXFORGE_OUTPUT_PRICE=4.50
export REFLEXFORGE_META_INPUT_PRICE=0.75
export REFLEXFORGE_META_OUTPUT_PRICE=4.50
reflexforge doctor

# Small paired baseline, at most $0.10 under the supplied standard token rates:
reflexforge benchmark preflight --tasks task_001 --conditions static,reflection \
  --max-api-calls 32 --max-tokens 16000 --max-usd 0.10
reflexforge benchmark run --tasks task_001 --conditions static,reflection \
  --max-api-calls 32 --max-tokens 16000 --max-usd 0.10
```

### Optimization pilot

The pilot selects two training and two dev tasks, lowers the common worker task budgets
to six steps and 6,000 tokens, requires a USD cap, and records the bank version. It can
verify execution but **cannot satisfy the five-distinct-dev-task promotion requirement**.
No genuine training failure means a normal no-failure stop, not a fabricated proposal.

```bash
reflexforge optimize --preset pilot --iterations 1 --repetitions 1 \
  --max-api-calls 60 --max-tokens 40000 --max-usd 0.25 --preflight-only
# Only after explicit approval to spend credits:
reflexforge optimize --preset pilot --iterations 1 --repetitions 1 \
  --max-api-calls 60 --max-tokens 40000 --max-usd 0.25
```

`--preset full` uses all 18 train and 12 dev tasks. Twelve distinct dev tasks can support
the strict policy, but adequate improvement and adequate execution budgets are still
required. Inspect preflight and choose explicit larger caps before authorizing a full
study. The default small caps deliberately do not guarantee completion of this large bank.
Use `--bank-version VERSION` to reject a changed bank. No full paid run was launched.

The strict gatekeeper itself is unchanged: no success regressions, bounded resource
consumption, at least five improved task IDs, and the existing conservative sign-test
criterion adjusted for the iteration limit. Exploratory statistics never promote a version.

### Evaluating an accepted meta configuration

After a real full optimization has actually accepted a bank-matched version:

```bash
reflexforge config-history
reflexforge benchmark run --split dev --conditions static,reflection,meta \
  --optimized-version ACCEPTED_VERSION --attempts 1 \
  --max-api-calls 80 --max-tokens 40000 --max-usd 0.25
```

Select `--tasks` for a small diagnostic comparison; do not interpret a truncated or small
study as improvement evidence. Reserve `--split test --final` for the predeclared final
comparison. For the seven fresh test tasks, select
`--tasks task_032,task_033,task_034,task_035,task_036,task_037,task_038`.
Repeated final evaluation can bias conclusions even though the CLI requires an explicit
`--final`; it is a research responsibility, not a claim that software can make data unseen.

## Exploratory analysis and reports

```bash
reflexforge benchmark compare EXPERIMENT_ID
reflexforge benchmark report --experiment EXPERIMENT_ID
# Synthetic plan or mocked experiment:
reflexforge benchmark report --experiment EXPERIMENT_ID --synthetic
# Empty real-data report, without model requests:
reflexforge benchmark report
```

Reports include success by execution configuration/condition, static difficulty and bug
category; tokens/cost per solved task; runtime/tool distributions; training failure labels;
matching-bank optimization acceptance history and candidate dev rates; and paired final
comparisons when supplied actual final-test results. Missing sections say pending. An
empty real-data report has been generated rather than populating example scores.

Paired analysis averages repeat outcomes within each task before bootstrapping tasks
(seed 2026, 2,000 draws), and reports an exact two-sided task-level sign probability.
Attempt-level Wilson intervals are descriptive only. Small samples, any missing pairs,
intervals covering zero, or weak sign evidence are explicitly inconclusive. Task correlations,
synthetic authoring biases, adaptive dev reuse, partial-run selection, nondeterministic
models and noisy wall time limit inference. Exploratory output always has `promotion=false`.

Real and synthetic reports use separate paths. A bank-version mismatch prevents reporting
against changed fixture labels. Old-bank optimization histories are excluded from current-bank
charts; their original audit stores remain available. Real benchmark metrics are never
filled from fixture QA or synthetic outcomes.

## Validation and limitations

All 38 buggy/reference fixture pairs passed actual Docker QA; expected splits and family
isolation, source/reference hashing, metadata separation, budget caps, interruption recovery,
explicit reflection feedback, matched sampling, all three conditions, and report generation
are covered by tests. Run all tests including existing Docker checks with:

```bash
REFLEXFORGE_DOCKER_TESTS=1 .venv/bin/python -m pytest -q
.venv/bin/ruff check src scripts tests
.venv/bin/ruff format --check src scripts tests
.venv/bin/python -m pip check
```

Final verification: **174 tests passed, zero failed, zero skipped**, with Docker enabled.
Lint, formatting, and dependency checks passed. Live baseline, reflection
and meta-optimized API execution were intentionally not exercised. Account permissions,
parameter acceptance on a chosen nondefault model, actual task difficulty, realistic
repository performance, and genuine self-improvement remain unverified. Docker shares a
kernel/VM boundary, hidden tests are readable by submitted code during evaluation, and
host-crash orphan cleanup remains subject to [existing security limitations](security.md).

This is ready for a small explicitly authorized pilot, not a claim of improved coding
ability or a completed large research study. SWE-bench, external repository integration,
strong adversarial grading, automatic paid-request replay, and out-of-sample research
conclusions remain outside this milestone.
