"""Private, create-only lifecycle artifacts for untrusted meta-generation output."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from reflexforge.storage.traces import Trace


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def response_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return response_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {k: response_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [response_value(v) for v in value]
    return {
        k: response_value(v)
        for k, v in vars(value).items()
        if not k.startswith("_") and not callable(v)
    }


class GenerationDiagnostics:
    def __init__(
        self,
        directory: Path,
        *,
        pilot_id: str,
        generation_attempt: int,
        accounting: Callable[[], dict] | None = None,
        prices: tuple | None = None,
    ):
        if any(p.is_symlink() for p in [directory, *directory.parents]):
            raise ValueError("diagnostic symlinks are forbidden")
        directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.parent.chmod(0o700)
        directory.mkdir(mode=0o700)  # Refuse reuse/overwrite of a previous attempt.
        self.directory, self.pilot_id, self.attempt = directory, pilot_id, generation_attempt
        self.accounting, self.prices = accounting, prices
        self.redactor = Trace(directory / "unused.jsonl", pilot_id)
        self.files: dict[str, str] = {}
        self.response_saved = False
        self.phase = "request"
        self.status = "started"
        self.before = None
        self.closed = False

    def write(self, name: str, value: Any):
        if self.closed:
            raise RuntimeError("diagnostic attempt is finalized; no new artifacts permitted")
        if Path(name).name != name:
            raise ValueError("diagnostic filenames must not escape their private directory")
        safe = self.redactor.sanitize(value)
        # JSON escaping is lossless and also preserves malformed Unicode model text.
        payload = (json.dumps(safe, indent=2, ensure_ascii=True) + "\n").encode()
        path = self.directory / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
            os.fchmod(file.fileno(), 0o400)
        self.files[name] = hashlib.sha256(payload).hexdigest()

    def begin(self, request: dict, max_output_tokens: int):
        self.before = self.accounting() if self.accounting else None
        payload = json.loads(request["input"][0]["content"])
        manifest = [
            {
                "run_id": f["run_id"],
                "events": [
                    {
                        "event_index": str(i),
                        "recorded_sha256": hashlib.sha256(e["recorded"].encode()).hexdigest(),
                        "stage": e.get("stage"),
                        "truncated": e.get("truncated", False),
                    }
                    for i, e in f["events"].items()
                ],
            }
            for f in payload["failures"]
        ]
        self.write(
            "request.json",
            {
                "label": "private_meta_diagnostic_input",
                "pilot_id": self.pilot_id,
                "generation_attempt": self.attempt,
                "role": "reflector",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "policy": payload.get("policy"),
                "request": request,
                "request_sha256": fingerprint(request),
                "stored_request_sha256": fingerprint(self.redactor.sanitize(request)),
                "secret_redaction_applied": self.redactor.sanitize(request) != request,
                "evidence_manifest": manifest,
                "evidence_sha256": fingerprint(payload["failures"]),
                "prices_per_million": self.prices,
                "generation_settings": {
                    "max_output_tokens": max_output_tokens,
                    "store": False,
                    "timeout_seconds": 30,
                    "sdk_retries": 0,
                    "service_tier": "default",
                },
                "accounting_before": self.before,
            },
        )
        self.phase = "generation"

    def capture_response(self, response: Any):
        if self.response_saved:
            return
        self.phase = "capture"
        raw = response_value(response)
        output_text = getattr(response, "output_text", None)
        self.write(
            "response.json",
            {
                "label": "UNTRUSTED_RAW_META_RESPONSE_NOT_VALIDATED",
                "received_utc": datetime.now(timezone.utc).isoformat(),
                "pilot_id": self.pilot_id,
                "generation_attempt": self.attempt,
                "raw_response": raw,
                "output_text": output_text,
                "received_response_sha256": fingerprint(raw),
                "secret_redaction_applied": self.redactor.sanitize(raw) != raw
                or self.redactor.sanitize(output_text) != output_text,
            },
        )
        self.response_saved = True
        self.phase = "accounting"

    def parsed(self, result: Any):
        self.write(
            "parsing.json",
            {
                "status": "passed",
                "label": "PARSED_NOT_EVIDENCE_VALIDATED",
                "reflection": result.model_dump(),
            },
        )
        self.phase = "validation"

    def validated(self, matches: list[dict]):
        self.write("validation.json", {"status": "passed", "citation_matches": matches})
        self.status = "validated"

    def failed(self, exc: BaseException):
        if "failure.json" in self.files:
            return
        category = (
            exc.details["failure_category"]
            if hasattr(exc, "details")
            else {
                "parsing": "structured_output_parsing",
                "validation": "reflection_validation",
                "capture": "raw_response_persistence",
                "accounting": "api_accounting",
            }.get(self.phase, "generation_or_capture")
        )
        error = {
            "status": "rejected",
            "phase": self.phase,
            "failure_category": category,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "details": getattr(exc, "details", None),
        }
        if hasattr(exc, "errors"):
            error["schema_errors"] = exc.errors(
                include_input=False, include_url=False, include_context=False
            )
        if self.phase == "parsing" and "parsing.json" not in self.files:
            self.write("parsing.json", error)
        if self.phase == "validation" and "validation.json" not in self.files:
            self.write("validation.json", error)
        self.write("failure.json", error)
        self.status = "rejected"

    def finish(self):
        for name in ("parsing.json", "validation.json"):
            if name not in self.files:
                self.write(name, {"status": "not_run"})
        after = self.accounting() if self.accounting else None
        delta = None
        if self.before is not None and after is not None:
            delta = {k: after[k] - self.before[k] for k in ("api_calls", "tokens")}
            before_usd = self.before.get("usd_upper_bound")
            if self.before["api_calls"] == 0 and self.prices is not None:
                before_usd = 0.0  # Empty priced ledger, not unknown/unpriced prior usage.
            if before_usd is not None and after.get("usd_upper_bound") is not None:
                delta["usd_upper_bound"] = after["usd_upper_bound"] - before_usd
        self.write(
            "accounting.json",
            {
                "cumulative_before": self.before,
                "cumulative_after": after,
                "generation_delta": delta,
            },
        )
        self.write(
            "manifest.json",
            {
                "label": "PRIVATE_REFLECTOR_DIAGNOSTIC_DO_NOT_FEED_TO_PROPOSER",
                "pilot_id": self.pilot_id,
                "generation_attempt": self.attempt,
                "status": self.status,
                "files_sha256": dict(self.files),
            },
        )
        self.closed = True
