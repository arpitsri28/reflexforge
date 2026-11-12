# Token-budget sensitivity — November 11, 2026

Recorded static-incumbent follow-up, separate from candidate evaluation and from the unchanged-budget baseline. Only the per-worker cumulative-token ceiling changes. Original source, task fixtures, evaluator, incumbent, step/time limits, tools, model, sampling, bank and image are preserved.

Study `f662545866a9481a9e9c94477d8a6d5e`; root `/private/tmp/reflexforge-token-sensitivity-2026-11-11-05k8p8b7`. One new attempt per selected task is an exploratory observation; it cannot establish that the cap caused or prevented a failure. Tasks were selected post-hoc because they had unsuccessful token-limited baseline attempts; this is not an out-of-sample score. These are project-authored fixtures, and dev tasks have prior exposure.
Child experiment IDs: `2c053c0826354176b9ca011dfc56825a`, `7ca29a61271a4c8a9c81a135e13316ec`.

```json
{
  "baseline_budget": {
    "max_steps": 20,
    "wall_seconds": 240,
    "command_seconds": 30,
    "max_tokens": 24000,
    "response_tokens": 2048,
    "retry_limit": 0
  },
  "new_budget": {
    "max_steps": 20,
    "wall_seconds": 240,
    "command_seconds": 30,
    "max_tokens": 40000,
    "response_tokens": 2048,
    "retry_limit": 0
  },
  "shared_caps": {
    "max_tokens": 160000,
    "max_api_calls": 180,
    "max_usd": 0.4
  }
}
```

| Task | Split | Earlier independent outcomes (24k) | Earlier protected checks | New independent outcome (40k) | New protected checks | New termination | New run ID |
| --- | --- | --- | --- | --- | --- | --- | --- |
| task_101 | train | failed, failed, failed | 5/6, 5/6, 5/6 | failed | 4/6 | completed | 1b2f328329fd4a10b66cf7ad85621c70 |
| task_102 | train | failed, failed, failed | 4/5, 3/5, 3/5 | failed | 3/5 | completed | 573fefccca5448069040a71545e1a5f8 |
| task_104 | train | failed, failed, failed | 4/5, 4/5, 3/5 | failed | 4/5 | completed | 02992dd178834cdf967342f31bdaada9 |
| task_108 | dev | failed, failed, failed | 4/5, 4/5, 4/5 | failed | 3/5 | step_limit | a19c9f85267c4a0982c97b2c7180d338 |


New observed full-task success among completed study runs: 0/4 = 0% (95% Wilson 0–48.98%). This sample is too small for broad conclusions. All planned study tasks have now run.

| Measure | Recorded value |
| --- | --- |
| Study ledger USD upper bound | 0.09252900 |
| Prior baseline + study ledger USD upper bound | 0.66811800 |
| API calls | 128 |
| False passes / fresh visible passes | 3/3 = 100% (95% Wilson 43.85–100%) |
| Ledger token count | 107612 |
| Worker SQLite rows | 4 |
| JSONL worker traces | 4 |
| Unmatched IDs | 0 |


USD uses recorded ledger upper-bound prices, not an invoice. The earlier interrupted baseline reservation remains included in the prior-baseline bound. No new uncertain usage or infrastructure failure was recorded.

| Task | Tokens | API calls | Tool calls | Wall seconds | Ledger USD upper bound | Visible after final edit? | Failed protected checks |
| --- | --- | --- | --- | --- | --- | --- | --- |
| task_101 | 19018 | 26 | 12 | 29.879334 | 0.01621725 | yes | __main__.Contract.test_account_and_key_delimiters_do_not_alias, __main__.Contract.test_pending_conflict |
| task_102 | 24644 | 30 | 14 | 26.899614 | 0.0212655 | yes | __main__.Contract.test_cancelled_acquisition_releases, __main__.Contract.test_cancelled_processing_retries |
| task_104 | 26882 | 32 | 15 | 33.201745 | 0.0235215 | yes | __main__.Contract.test_type_validation |
| task_108 | 37068 | 40 | 20 | 45.902364 | 0.03152475 | yes | __main__.Contract.test_false_and_zero, __main__.Contract.test_precedence |


All worker results reconcile with trace run_end, evaluator events and model/tool counters. Every shared-ledger ticket maps uniquely to a worker; tokens reconcile with recorded usage. Config comparison confirms that policy and tools match the matched baseline; the changed budget is recorded as an execution parameter, not a candidate.

Reproduce: `.venv/bin/python scripts/analysis_resume/report_sensitivity.py`. Exact SQL and bound parameters are in `evidence/queries.json`; run metadata, trace paths, check details and ledger tickets are in `evidence/evidence.json`; matched baseline run IDs and all displayed numbers are in comparison.json.
