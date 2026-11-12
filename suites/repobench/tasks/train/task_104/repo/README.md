# Mixed Source Etl

The pipeline accepts CSV rows with amount as an exact two-decimal major-unit string, or JSON rows
 with amount_cents as a nonnegative integer (booleans are invalid). sale_id is unique per logical sale.
 Currency codes are case-insensitive and are emitted uppercase. Timestamps require an ISO timezone and
 daily buckets use UTC. Duplicates across sources count once; conflicting duplicates raise ValueError.
 Invalid rows are returned as indexed errors and do not contribute to totals. Export amounts are integer
 minor units. Processing several batches must agree with processing their concatenation.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
