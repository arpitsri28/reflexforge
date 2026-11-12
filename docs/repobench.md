# ReflexForge RepoBench — Milestone 3.5

RepoBench adds 12 project-authored repository debugging tasks, separate from the original
38-task `debug` suite: **6 train, 4 dev, 2 held-out test**. Each application has 7 meaningful
source modules, except authorization with 8 (85 total), plus public unittest checks and a
documented functional contract. The worker, sandbox, independent evaluator and strict
Gatekeeper retain their existing behavior. No paid OpenAI experiment was executed during
implementation. Docker fixture validation is evidence about the fixtures, not agent scores.

See [inventory](repobench-inventory.md) for domains, module counts and test counts.

## Verification recorded on November 8, 2026

- All 12 final-manifest Docker QA receipts pass: buggy baselines rejected, references
  accepted, incomplete repairs rejected, deterministic repetitions and isolation verified.
- Fixture suites contain 25 public and 61 hidden test methods across the repositories.
- `REFLEXFORGE_DOCKER_TESTS=1 .venv/bin/pytest -q`: **198 passed** (76.92 seconds).
- Ruff lint and formatting checks pass. CLI inventory reports all 12 fixtures valid.
- `reflexforge doctor`: API key configured `true`, Docker ready, image ready; no API probe.
- Live LLM behavior and empirical task difficulty remain unverified; no paid calls were made.

## Layout and versioning

`suites/repobench/tasks/SPLIT/ID/repo/` contains worker-visible application source,
README contracts and public tests. Sibling `task.json` holds the issue, reproduction
command, budgets and source allowlist. Sibling `hidden.py` stays with the trusted controller.
`suites/repobench/benchmark/` holds the versioned manifest, private reference overlays,
deliberately incomplete repair overlays, private structural/root-cause specification and
recorded QA report. These files are never uploaded to a worker container or meta prompt.
The authoring catalog and inventory are researcher material, not worker context.

The manifest hashes source, public/hidden tests, task metadata, reference overlays and the
private specification; that specification also hashes incomplete repair overlays. Changing
any of these creates a new version. `scripts/build_repobench.py` materializes trusted source
strings without executing fixture code. It archives each new version in
`suites/repobench/versions/HASH/`; existing archived directories are never overwritten.
To reconstruct a historical bank, copy its archived `tasks` and `benchmark` into a separate
project's `suites/repobench`, alongside the desired configuration. `--bank-version` verifies
the selected active bank; it does not silently switch archives. Revalidate the restored bank
against the selected Docker image before running an agent.

Runtime results live in `artifacts/benchmark/repobench/{real,synthetic,qa}`. Optimization
uses `artifacts/optimization/repobench/{real,synthetic}` with its own Git configuration
history and active pointer. The original suite keeps its original paths. Every experiment
records suite, manifest version, selected tasks, configuration source/execution hashes,
model, sampling, image, budgets and API ledger. Individual completed cells also record
suite/version, condition, attempt, budgets, tokens, runtime, tool calls and evaluation.

## Reproducible validation without API charges

```bash
source .venv/bin/activate
docker build -t reflexforge-sandbox:local -f src/reflexforge/sandbox/Dockerfile .
reflexforge benchmark list --suite repobench
reflexforge benchmark validate --suite repobench --structure-only
reflexforge benchmark validate --suite repobench --workers 2
REFLEXFORGE_DOCKER_TESTS=1 pytest -q
ruff check src tests scripts
# Original bank remains selectable:
reflexforge benchmark list --suite debug
```

Validation runs all fixture code in fresh, offline Docker containers with the existing
resource restrictions. For each task it verifies public baseline failure, independent
unmodified-submission rejection, reference public/hidden success, and an incomplete fix
that passes public tests but fails hidden tests. Baseline and reference hidden evaluations
each run twice; structured test outcomes must agree. Checks cover exact test counts,
source/reference/mutant hashes, private-file absence from worker uploads and image ID.
Failed QA prevents a real benchmark run. Receipts are stored under
`artifacts/benchmark/repobench/qa/HASH/`; the supplied consolidated record is
`suites/repobench/benchmark/validation.json`.

For fixture development, select a subset with `--tasks task_101,task_102`. Run full QA
after finalizing a bank. The original fixtures and evaluator are not modified to obtain
passing results. Hidden tests execute only in independent evaluation and their output is
excluded from worker retries and meta-agent evidence.

## Small real baseline — commands only

These commands were not executed during implementation. Run from the repository root
with Docker running and QA complete. The repository-root `.env` is loaded automatically;
explicit exported values take precedence. For a session key in the default zsh shell:

```bash
source .venv/bin/activate
read -r -s 'OPENAI_API_KEY?OpenAI API key: '
echo
export OPENAI_API_KEY
export OPENAI_MODEL=gpt-5.4-mini
reflexforge doctor
# Supply the current USD-per-million-token rates for your selected model/account.
read 'REFLEXFORGE_INPUT_PRICE?Input USD per million tokens: '
read 'REFLEXFORGE_OUTPUT_PRICE?Output USD per million tokens: '
export REFLEXFORGE_INPUT_PRICE REFLEXFORGE_OUTPUT_PRICE
reflexforge benchmark preflight --suite repobench --split train --tasks task_101 \
  --conditions static --attempts 1 --max-api-calls 40 --max-tokens 24000 --max-usd 0.15
# This next command makes paid requests only when you choose to execute it:
reflexforge benchmark run --suite repobench --split train --tasks task_101 \
  --conditions static --attempts 1 --max-api-calls 40 --max-tokens 24000 --max-usd 0.15
reflexforge benchmark report --suite repobench
```

This schedules one training task. The CLI gives RepoBench 20 generation steps, 24,000
combined tokens, 2,048 output tokens per response, 240 worker seconds, 30 command seconds,
zero SDK retries and the existing function-call ceiling. Static, reflection and candidate
conditions use identical budgets/tools and a fixed model with temperature 0 and reasoning
effort `none`. Task limits still apply. Programmatic settings can select compatible
sampling for another model. Reservations include counted input plus maximum output; a
cap may stop the task early. Counting calls consume the HTTP-call cap. Unknown usage
halts further requests. A small cap is protection, not a promise the task will finish.

Use `benchmark run ... --dry-run` for a stored synthetic plan with pending outcomes;
it creates neither API nor Docker clients. Never interpret synthetic plans as task scores.
For an A/B study, repeat the same preflight/run with `--conditions static,reflection` and
an explicitly chosen overall budget. It schedules two runs per selected task.

## Optimization and exploratory comparisons

`reflexforge optimize --suite repobench` freezes only train/dev contracts. References,
private explanations, repair overlays and held-out tasks are excluded. Meta evidence
continues through the existing sanitization boundary. All calls share the durable global
request/token/USD ledger. Worker and meta pricing must both be configured for a USD cap.

First inspect an inexpensive pilot without making requests:

```bash
export OPENAI_META_MODEL="$OPENAI_MODEL"
export REFLEXFORGE_META_INPUT_PRICE="$REFLEXFORGE_INPUT_PRICE"
export REFLEXFORGE_META_OUTPUT_PRICE="$REFLEXFORGE_OUTPUT_PRICE"
reflexforge optimize --suite repobench --preset pilot --iterations 1 \
  --max-api-calls 40 --max-tokens 24000 --max-usd 0.15 --preflight-only
```

The strict Gatekeeper still requires improvements on at least five distinct development
tasks and its existing statistical/resource checks. **Four dev tasks cannot satisfy it.**
Repeated attempts do not create independent tasks. Expand independent development
coverage in a new benchmark version before attempting strict promotion; never reuse the
two held-out repositories for that purpose. The legacy optimizer mock demonstration is
debug-only; RepoBench supports benchmark planning and optimizer preflight instead.

For an explicitly exploratory candidate, copy `config` into a separate `candidate-config`
directory and edit approved prompt/workflow/skill files. Then inspect and, only if desired,
execute a paired development evaluation:

```bash
reflexforge benchmark preflight --suite repobench --split dev --tasks task_107 \
  --conditions static,candidate --max-api-calls 40 --max-tokens 24000 --max-usd 0.15
reflexforge benchmark run --suite repobench --split dev --tasks task_107 \
  --conditions static,candidate --candidate-config candidate-config \
  --max-api-calls 40 --max-tokens 24000 --max-usd 0.15
reflexforge benchmark compare EXPERIMENT_ID --suite repobench
reflexforge benchmark report --experiment EXPERIMENT_ID --suite repobench
```

Candidate evaluation requires an explicit path, validates the approved configuration tree
and rejects changes to execution budgets or tool configuration. It cannot promote or
update the active pointer. The `meta` condition retains its requirement for real accepted
history from the same suite/bank/model via `--optimized-version`. Suite-aware
`config-history`, `proposals`, `show-iteration` and `rollback-config` inspect the separate
optimization store. Reserve `--split test --final` for a final frozen comparison.

Reports include paired task-level comparisons, failure classifications, tool calls,
tokens, runtime, cost, unresolved usage and proposal history. Infrastructure failures,
unfinished cells and coding failures remain distinct. Small samples are exploratory;
do not claim statistical significance or self-improvement from fixture QA.

## Limitations

These compact, standard-library applications are project-authored simulations, not
independently sourced production incidents. Functional modules and cross-module state
contracts provide more breadth than the original bank, but empirical difficulty is
unmeasured. All provisional labels are `hard`; they are hypotheses rather than measured
agent failure rates. Longest static import depth is reported separately from injected
runtime dependencies and the private symptom-to-cause investigation path.

Two repeated deterministic runs and one incomplete repair per task provide finite QA
coverage, not exhaustive proofs. Tests use controlled events/failure injection rather
than timing races. The existing Python evaluator is suitable for cooperative debugging
experiments, not adversarial patch certification; see [security limitations](security.md).
The authoring assistant necessarily saw private and held-out material; worker exposure
flags refer to agent experiments, not benchmark authorship. Prevent sharing researcher
files with evaluated agents. No real baseline, reflection, meta or held-out agent scores
are available yet, and no empirical improvement is claimed.
