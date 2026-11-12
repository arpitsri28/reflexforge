### Exploratory token-budget sensitivity

A separate follow-up selected task_101, task_102, task_104 and task_108 after unsuccessful
token-limited baseline attempts and reran each once. Only the worker token ceiling rose
from 24,000 to 40,000. Policy, model, tools, fixtures and
the other execution limits stayed fixed. This was a budget-sensitivity study, not a candidate.

| Task | Checks at 24k (three earlier attempts) | Checks at 40k | Termination |
| --- | --- | --- | --- |
| task_101 | 5/6, 5/6, 5/6 | 4/6 | completed |
| task_102 | 4/5, 3/5, 3/5 | 3/5 | completed |
| task_104 | 4/5, 4/5, 3/5 | 4/5 | completed |
| task_108 | 4/5, 4/5, 4/5 | 3/5 | step_limit |


Full-task success: **0/4 = 0% (95% Wilson 0–48.98%)**. No full-task improvement was observed
in these selected attempts; this small follow-up cannot establish a causal token-budget effect.
Task_108 reached the unchanged step limit, illustrating that other execution limits can bind.

The study recorded 128 API calls, 107,612 tokens, and a ledger USD upper
bound of **$0.092529**, below its shared $0.40 cap. Reproduce the comparison with

```bash
.venv/bin/python scripts/analysis_resume/report_sensitivity.py
```
