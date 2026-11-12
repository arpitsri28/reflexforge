# RepoBench inventory

Immutable bank version: `e39bbb6312fc8a29e3a4dacb23a68fbe74b1cb037180df86b12a2aac49148fc6`.

Twelve project-authored repositories: **6 train / 4 dev / 2 test**, **85 meaningful source modules**.
All difficulty labels are provisionally hard; empirical difficulty and agent scores remain pending.
No paid model evaluations were run. Private explanations, dependency investigation paths,
reference overlays and incomplete repairs remain in the controller-owned benchmark directory.

| Task | Split | Domain | Bug category | Source modules | Static import depth | Public tests | Hidden tests |
|---|---|---|---|---:|---:|---:|---:|
| task_101 | train | backend-payments | Retry identity / pending operation consistency | 7 | 2 | 3 | 6 |
| task_102 | train | async-job-ownership | Atomic ownership / cancellation recovery | 7 | 1 | 2 | 5 |
| task_103 | train | message-delivery | Acknowledgment / transactional deduplication | 7 | 1 | 2 | 4 |
| task_104 | train | mixed-source-etl | Schema normalization / monetary units | 7 | 2 | 2 | 5 |
| task_105 | train | nested-ledger-transactions | Nested savepoints / live state ownership | 7 | 2 | 2 | 5 |
| task_106 | train | resumable-catalog-client | Durable pagination checkpoints | 7 | 1 | 2 | 5 |
| task_107 | dev | request-authorization | Authorization cache isolation / invalidation | 8 | 1 | 2 | 6 |
| task_108 | dev | service-configuration | Layer precedence / mutable ownership | 7 | 2 | 2 | 5 |
| task_109 | dev | worker-pool-lifecycle | Partial initialization / cleanup exceptions | 7 | 2 | 2 | 5 |
| task_110 | dev | streaming-event-protocol | Byte framing / incremental decoding | 7 | 3 | 2 | 5 |
| task_111 | test | dependency-container | Provider resolution / failed construction state | 7 | 2 | 2 | 5 |
| task_112 | test | search-projections | Index replacement / atomic validation | 7 | 2 | 2 | 5 |

Source counts exclude README and public tests. Each named module has an application role;
there are no empty padding modules. Static depth counts edges in the longest local import
path. Dependency injection and runtime calls introduce additional cross-module relationships.
The private specification records module roles, the symptom-to-cause investigation path,
plausible failure locations, debugging operations and interacting invariants.

## Docker QA

Every original fails its public reproduction and independent hidden evaluation. Every
reference passes both. Every deliberately incomplete repair passes the public suite and
fails private regression checks. Baseline/reference hidden checks run twice with identical
structured outcomes. All worker snapshots exclude hidden tests, references and private metadata.

The consolidated machine-readable results are in
[validation.json](../suites/repobench/benchmark/validation.json). They contain individual
exit statuses, test counts, failure identifiers, immutable source/reference/mutant hashes,
manifest hash, image ID, determinism and isolation checks. These are fixture QA results,
not measured worker success rates. Reproduce with:

```bash
.venv/bin/reflexforge benchmark validate --suite repobench --workers 2
```

## Repository components

### task_101: backend-payments

`models.py`, `journal.py`, `gateway.py`, `audit.py`, `payments.py`, `transport.py`, `api.py`.

### task_102: async-job-ownership

`jobs.py`, `broker.py`, `results.py`, `worker.py`, `operations.py`, `scheduler.py`, `application.py`.

### task_103: message-delivery

`messages.py`, `broker.py`, `storage.py`, `handlers.py`, `consumer.py`, `simulation.py`, `application.py`.

### task_104: mixed-source-etl

`sources.py`, `validation.py`, `normalization.py`, `aggregation.py`, `pipeline.py`, `exporting.py`, `application.py`.

### task_105: nested-ledger-transactions

`storage.py`, `transactions.py`, `accounts.py`, `fees.py`, `transfers.py`, `reporting.py`, `application.py`.

### task_106: resumable-catalog-client

`protocol.py`, `transport.py`, `client.py`, `decoding.py`, `checkpoint.py`, `destination.py`, `synchronizer.py`.

### task_107: request-authorization

`models.py`, `repository.py`, `authentication.py`, `policy.py`, `cache.py`, `service.py`, `middleware.py`, `application.py`.

### task_108: service-configuration

`defaults.py`, `parsing.py`, `layers.py`, `resolver.py`, `mailer.py`, `scheduler.py`, `application.py`.

### task_109: worker-pool-lifecycle

`resources.py`, `cleanup.py`, `pool.py`, `worker.py`, `telemetry.py`, `configuration.py`, `application.py`.

### task_110: streaming-event-protocol

`encoding.py`, `framing.py`, `schema.py`, `payloads.py`, `router.py`, `session.py`, `stream.py`.

### task_111: dependency-container

`definitions.py`, `registry.py`, `errors.py`, `factories.py`, `loader.py`, `providers.py`, `application.py`.

### task_112: search-projections

`documents.py`, `tokenization.py`, `storage.py`, `indexing.py`, `query.py`, `facets.py`, `service.py`.

## Research limits

The applications are compact offline simulations authored for this project. Four development
tasks cannot satisfy the unchanged Gatekeeper requirement of five improved distinct tasks.
Candidate comparisons are exploratory and never promote configurations. Two held-out tasks
must remain outside optimization and development decisions. Repeated deterministic tests
and one incomplete repair per task do not prove complete behavioral or adversarial coverage.
See [RepoBench workflow](repobench.md) for capped commands, isolation boundaries and study limits.
