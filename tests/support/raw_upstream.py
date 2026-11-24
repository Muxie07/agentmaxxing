"""A hand-rolled upstream that emits odd bytes, to test pass-through and malformed output.

For every request line it writes: a garbage line, then a response with unusual spacing.
"""

from __future__ import annotations

import json
import sys

for raw in sys.stdin.buffer:
    try:
        msg = json.loads(raw)
    except ValueError:
        continue
    if not isinstance(msg, dict) or "id" not in msg:
        continue
    sys.stdout.buffer.write(b"this is { not json\n")
    body = b'{ "jsonrpc" : "2.0" ,  "id" : ' + json.dumps(msg["id"]).encode()
    body += b' , "result" : { "content" : [ ] , "isError" : false , "marker" : "\xc3\xa9" } }\n'
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()
