# Backend Payments

PaymentService exposes submit(account, key, amount, currency='USD') through API.post().
 Amounts are positive integer minor units. A checkout key is scoped to an account. Identical
 retries return the same receipt and perform one provider charge. A different amount or
 currency under an existing key raises ValueError. ReplyLost means the provider may have
 accepted the charge; it is the only automatically retryable error. Failed validation must
 not allocate a charge. Audit records describe successful logical checkouts once each.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
