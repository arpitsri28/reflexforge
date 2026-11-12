# Request Authorization

Requests authenticate a token to the current principal. Documents and principals belong to tenants.
 Owners and tenant admins may read a document; ordinary members may read only public documents.
 Cross-tenant access is always denied. Changing roles, ownership or public visibility must affect the next
 request. Repeated equivalent requests should reuse authorization decisions. Returned content must
 be isolated from the repository's mutable data. Invalid tokens raise PermissionError.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
