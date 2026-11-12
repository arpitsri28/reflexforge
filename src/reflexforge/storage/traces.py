import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any


class Trace:
    def __init__(self, path: Path, run_id: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.run_id = run_id
        self.lock = threading.Lock()
        self.secrets = [
            v
            for k, v in os.environ.items()
            if len(v) >= 8
            and any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        ]

    def redact(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)

    def sanitize(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {self.redact(str(k)): self.sanitize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.sanitize(v) for v in value]
        return value

    def event(self, kind: str, data: Any) -> None:
        payload = {
            "schema_version": 1,
            "run_id": self.run_id,
            "time": time.time(),
            "kind": kind,
            "data": data,
        }
        line = json.dumps(self.sanitize(payload), ensure_ascii=False)
        with self.lock, self.path.open("a") as file:
            file.write(line + "\n")
            file.flush()
            os.fsync(file.fileno())
