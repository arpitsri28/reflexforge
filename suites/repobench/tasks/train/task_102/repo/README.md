# Async Job Ownership

Jobs transition queued -> leased -> done; cancellation or processing failure makes an unfinished job
 available again. At most one live worker owns a job. The before_claim hook is an instrumentation
 scheduling point and may await; keep it functional. Results are keyed by job ID and successful
 processing is acknowledged after the result is stored. No wall-clock sleeps are needed for tests.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
