# Benchmark inventory

Version: `d47b31353fc8ee339a3d293dc88b1f6861b1c6febe5e4e48d525bb1d84790e94`.

Project-authored synthetic fixtures. All 38 validated by original-fails/reference-passes Docker QA.
Difficulty labels are static authoring metadata, not measured agent difficulty.
The original three tasks have prior agent exposure; the test split has seven fresh tasks.

## Split and difficulty counts

| Split | Easy | Medium | Hard | Total |
| --- | ---: | ---: | ---: | ---: |
| train | 1 | 11 | 6 | 18 |
| dev | 1 | 6 | 5 | 12 |
| test | 1 | 3 | 4 | 8 |

## Bug categories

| Category | Count |
| --- | ---: |
| algorithms | 1 |
| analytics | 1 |
| async | 2 |
| authentication | 1 |
| authorization | 1 |
| cache | 3 |
| concurrency | 1 |
| configuration | 2 |
| datetime | 1 |
| enabled-record-predicate | 1 |
| encoding | 1 |
| errors | 1 |
| events | 1 |
| imports | 2 |
| lifecycle | 2 |
| one-based-page-index | 1 |
| pagination | 1 |
| parsing | 1 |
| pipeline | 2 |
| protocol | 1 |
| retry | 1 |
| routing | 1 |
| serialization | 3 |
| slice-boundary | 1 |
| sorting | 1 |
| state | 3 |
| validation | 1 |

## Fixture coverage

Affected modules counts source files changed by the reference fix; it does not estimate empirical difficulty.

| Task | Split | Difficulty | Category | Affected modules | Expected regression coverage | QA |
| --- | --- | --- | --- | ---: | --- | --- |
| task_001 | train | easy | slice-boundary | 1 | reported reproduction, empty input, boundary behavior | valid |
| task_002 | dev | easy | one-based-page-index | 1 | reported reproduction, empty input, boundary behavior | valid |
| task_003 | test | easy | enabled-record-predicate | 1 | reported reproduction, empty input, boundary behavior | valid |
| task_004 | train | medium | state | 1 | overlapping carts, atomic rejection, cancellation | valid |
| task_005 | train | medium | cache | 1 | tenant separation, cache hit, scoped invalidation | valid |
| task_006 | train | medium | cache | 1 | insert invalidation, delete invalidation, defensive copies | valid |
| task_007 | train | hard | async | 1 | awaiting, order and multiplicity, empty input | valid |
| task_008 | train | medium | retry | 1 | transient recovery, permanent error propagation, invalid attempt count | valid |
| task_009 | train | medium | configuration | 1 | normalization, defaults, invalid inputs | valid |
| task_010 | train | medium | serialization | 1 | precision, negative and fractional amounts, wire type | valid |
| task_011 | train | medium | authorization | 1 | organization boundary, owner/admin privileges, ordinary member denial | valid |
| task_012 | train | medium | imports | 1 | package import, multiple lines, unknown product propagation | valid |
| task_013 | train | medium | pipeline | 1 | one-shot iteration, empty input, zero and negative values | valid |
| task_014 | train | medium | lifecycle | 1 | success cleanup, exception cleanup, propagation | valid |
| task_015 | train | hard | pagination | 1 | empty intermediate page, terminal nonempty page, cursor cycles | valid |
| task_016 | train | hard | validation | 1 | shared dependencies, cycle and self-cycle, unknown nodes | valid |
| task_017 | train | hard | state | 1 | safe replay, conflicting request, failure not cached | valid |
| task_018 | train | hard | state | 1 | nested rollback, commit, exception propagation | valid |
| task_019 | dev | medium | sorting | 1 | stable ties, descending order, input isolation | valid |
| task_020 | dev | hard | concurrency | 1 | deterministic interleaving, unique increments, empty batch and reuse | valid |
| task_021 | dev | hard | datetime | 2 | offset normalization, chronological order, timezone validation and stable ties | valid |
| task_022 | dev | hard | authentication | 1 | single use, replay denial, expiry boundary | valid |
| task_023 | dev | medium | serialization | 1 | quoted delimiters, embedded line breaks, empty values | valid |
| task_024 | dev | medium | cache | 1 | hit recency, replacement recency, capacity enforcement | valid |
| task_025 | dev | hard | async | 1 | successful gather, sibling cancellation, awaited cleanup and propagation | valid |
| task_026 | dev | medium | parsing | 1 | scheme validation, whitespace handling, field count | valid |
| task_027 | train | medium | errors | 1 | partial results, error positions, infrastructure propagation | valid |
| task_028 | dev | hard | configuration | 1 | recursive merge, input ownership, scalar replacement | valid |
| task_029 | dev | medium | pipeline | 1 | partial final batch, empty/exact batches, size validation | valid |
| task_030 | train | hard | lifecycle | 1 | LIFO teardown, partial acquisition failure, empty resource group | valid |
| task_031 | dev | medium | routing | 1 | literal precedence, segment boundaries, unknown paths | valid |
| task_032 | test | hard | protocol | 1 | fragment buffering, multiple/empty frames, state reuse | valid |
| task_033 | test | hard | algorithms | 1 | nested ranges, adjacency and gaps, empty/reversed intervals | valid |
| task_034 | test | hard | serialization | 2 | legacy default, new schema, unknown schema rejection | valid |
| task_035 | test | medium | events | 1 | self-unsubscribe, new handlers deferred, repeated dispatch | valid |
| task_036 | test | medium | analytics | 1 | partition invariance, unequal weights, zero weights | valid |
| task_037 | test | medium | encoding | 1 | reserved characters, repeated parameters, Unicode and empty lists | valid |
| task_038 | test | hard | imports | 1 | lazy import, idempotent initialization, missing plugin | valid |
