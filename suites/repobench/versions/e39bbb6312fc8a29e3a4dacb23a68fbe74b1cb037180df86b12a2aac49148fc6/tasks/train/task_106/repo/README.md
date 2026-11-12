# Resumable Catalog Client

Transport is local and supports HTTP-like response statuses. Retryable 503 responses use a bounded
 request-attempt policy and repeat the same cursor. Nonretryable errors propagate. A checkpoint stores
 the next uncommitted page; completed synchronization is distinct from an initial None cursor. Product
 pages are validated before applying a transactional destination batch. A failed batch or invalid page
 must remain retryable at its previous checkpoint. Product IDs are upsert keys; final output is ID-sorted.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
