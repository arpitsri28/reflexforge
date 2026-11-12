# Streaming Event Protocol

Each frame is a four-byte unsigned big-endian payload byte length followed by one UTF-8 JSON object.
 Maximum payload length is 65536 bytes. receive() may be called with any fragmentation, including one
 byte at a time and several frames per call. Events have positive integer seq and kind 'add' or 'ping'.
 Add events have integer amount and string label; booleans are not integers. Session effects are applied
 in increasing sequence; a repeated or older validated event is ignored. Invalid events do not advance
 the sequence or mutate totals. Inputs/outputs are local byte strings, not network sockets.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
