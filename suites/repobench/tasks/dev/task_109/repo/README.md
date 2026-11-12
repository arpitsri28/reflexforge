# Worker Pool Lifecycle

Factories return closeable resources. open() may allocate before raising; validate() may also fail.
 close() is idempotent and safe before open. On startup failure, close every returned resource in reverse
 acquisition order, preserve the original startup exception, record cleanup error strings, and leave
 the pool stopped/restartable. Successful shutdown drains workers before closing resources; repeating
 shutdown is a no-op. Do not depend on garbage collection to release connections.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
