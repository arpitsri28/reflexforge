# Implementation checkpoints

## Milestone 1 — worker live runs reported; Docker integration verified

Implemented task/config schemas, three debugging fixtures, seven worker tools, OpenAI
SDK loop, Docker lifecycle and limits, independent evaluator, patches, JSONL/SQLite, and
basic CLI. Tests cover controller behavior and SDK HTTP serialization without model spend.
The user reported successful real worker runs for all three fixtures. During Milestone 2,
the five Docker integration tests passed. Lint, formatting and dependency checks pass.
Those repairs do not establish persistent configuration improvement.

Reproduce local checks:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/reflexforge run-worker --task task_001 --dry-run
.venv/bin/reflexforge report
```

Required next verification:

```bash
docker build -t reflexforge-sandbox:local -f src/reflexforge/sandbox/Dockerfile .
REFLEXFORGE_DOCKER_TESTS=1 .venv/bin/python -m pytest -q -m docker
# Export OPENAI_API_KEY first; OPENAI_MODEL defaults to gpt-5.4-mini.
.venv/bin/reflexforge run-worker --task task_001
```

The user subsequently reported successful real worker repairs on all three fixtures.
That verifies the Milestone 1 path, not persistent configuration improvement.

## Milestone 2 — implemented; live meta generation not exercised

Implemented the reflector/proposer, grounded train-only evidence, strict candidate allowlist,
complete Git snapshots, isolated paired dev runs, conservative deterministic gatekeeper,
rollback, API call/token/USD reservations, synthetic/real separation, and interruption
recovery. Mocked acceptance, rejection, and no-failure cycles are demonstrated without
spending API credits. The final suite passed **110 tests with Docker enabled**, with zero
failures and zero skipped; lint, formatting, and dependency checks passed. No genuine
improvement is claimed.

See [Milestone 2 documentation](milestone-2.md) for exact commands and limitations. The
single-task dev bank cannot justify real acceptance under the conservative gate.

## Milestone 3 — implemented; real benchmark measurements pending

The bank has 38 tasks split 18/12/8, with private reference fixes, versioned metadata and
recorded Docker QA for every original/reference pair. Static, within-task reflection and
accepted-meta comparisons use shared budgets and paired outcomes. Exploratory analysis
never promotes a configuration. Reports preserve missing data and distinguish legacy
exposure: seven held-out tasks are fresh; task_003 was previously exercised in Milestone 1.

Final verification: **174 passed, zero failed, zero skipped**, with Docker enabled. Lint,
formatting and dependency checks passed. No paid API calls or real experiments were run.
See [Milestone 3](milestone-3.md) and [fixture inventory](benchmark-inventory.md).

## Milestone 4 — planned

Resumable iteration state, graceful/hard interruption handling, stale-container cleanup,
integration and API smoke runs, frozen image and task revisions, and a reproducible
end-to-end demonstration with actual recorded outcomes.

Milestone 3.5 adds the separate [RepoBench suite](repobench.md), with a
[12-repository inventory](repobench-inventory.md), Docker fixture QA, suite-isolated
experiments and exploratory candidate evaluation. Empirical difficulty remains pending.
