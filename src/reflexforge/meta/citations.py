"""Literal matches against retained evidence only; never reread a full/private trace."""

import hashlib
import json
from typing import Any, Iterable


def text_match(quote: str, texts: Iterable[str]) -> str | None:
    texts = list(texts)
    if any(quote in text for text in texts):
        return "exact"
    # CRLF and LF represent the same line boundary. Do not collapse spaces, tabs,
    # indentation, punctuation, case, or token order; those can change source meaning.
    normalized = quote.replace("\r\n", "\n")
    if any(normalized in text.replace("\r\n", "\n") for text in texts):
        return "line_endings"
    return None


def supplied_strings(recorded: str) -> list[str]:
    """Decode only complete JSON that was itself retained and supplied to the model."""
    try:
        data = json.loads(recorded)
    except (ValueError, TypeError):
        return []  # Never recover missing suffixes from an unfiltered source file.
    strings = []

    def visit(value: Any):
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    # Function arguments are a JSON string inside the event JSON. A code quotation
    # copied from arguments.content must not require guessing two escaping layers.
    if isinstance(data, dict) and data.get("kind") == "tool_call":
        arguments = data.get("data", {}).get("arguments")
        if isinstance(arguments, str):
            try:
                visit(json.loads(arguments))
            except ValueError:
                pass
    return strings


def quote_match(quote: str, recorded: str) -> str | None:
    if quote in recorded:
        return "exact_supplied_text"
    if text_match(quote, [recorded]) == "line_endings":
        return "line_endings_supplied_text"
    match = text_match(quote, supplied_strings(recorded))
    return None if match is None else match + "_decoded_string"


class CitationValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        location: str,
        run_id: str,
        event_index: int,
        run_exists: bool,
        row: dict | None,
        quote: str,
        reason: str,
    ):
        self.details = {
            "failure_category": "citation_validation",
            "reason": reason,
            "location": location,
            "run_id": run_id,
            "event_index": event_index,
            "trace_line": event_index + 1,
            "run_exists": run_exists,
            "event_exists": row is not None,
            "event_truncated": row.get("truncated", False) if row else None,
            "supplied_event_stage": row.get("stage") if row else None,
            "quote_status": "absent_from_supplied_event"
            if reason == "quote_mismatch"
            else "present_but_wrong_stage"
            if reason == "wrong_stage"
            else "not_checked",
            "quote_sha256": hashlib.sha256(quote.encode("utf-8", "surrogatepass")).hexdigest(),
            "quote_length": len(quote),
        }
        # Do not place arbitrary model quotations or event contents in general logs.
        label = run_id if run_exists else "<not-supplied>"
        super().__init__(
            f"{message}; location={location}; run_id={label}; event_index={event_index}; "
            f"event_exists={row is not None}; reason={reason}"
        )


class ReflectionValidationError(ValueError):
    def __init__(self, message: str, *, location: str, reason: str, **context):
        self.details = {
            "failure_category": "reflection_validation",
            "location": location,
            "reason": reason,
            **context,
        }
        super().__init__(f"{message}; location={location}; reason={reason}")
