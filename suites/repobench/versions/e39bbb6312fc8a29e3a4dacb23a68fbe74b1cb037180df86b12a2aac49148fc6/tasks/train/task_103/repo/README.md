# Message Delivery

The broker supplies at-least-once delivery. Unacknowledged messages may be redelivered; acknowledged
 messages are removed. An event key identifies one logical balance delta. Applying the delta and recording
 its processed identity must succeed together. Handler failures propagate; retrying the same message
 after recovery must work. The simulation is entirely local and exposes deterministic failure injection.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
