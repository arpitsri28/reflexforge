# Nested Ledger Transactions

Ledger holds account balances and an audit list. Transactions support nested savepoints. An inner
 rollback restores its entry state and may be caught by outer code; an outer rollback restores all
 outer-entry state, including inner committed changes. Existing account dictionary views and audit
 list views remain live across rollback. Original exceptions propagate. Balances cannot become negative.
 Transfers and fee charges use the same transaction manager and must not leave partial effects.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
