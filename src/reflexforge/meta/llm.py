import json
from typing import Any, TypeVar

from pydantic import BaseModel

from reflexforge.meta.budget import BudgetedClient
from reflexforge.meta.diagnostics import GenerationDiagnostics

T = TypeVar("T", bound=BaseModel)


def structured_call(
    client: Any,
    model: str,
    schema: type[T],
    instructions: str,
    payload: dict[str, Any],
    max_output_tokens: int,
    *,
    diagnostics: GenerationDiagnostics | None = None,
) -> T:
    common = dict(
        model=model,
        instructions=instructions,
        input=[{"role": "user", "content": json.dumps(payload)}],
        text={
            "format": {
                "type": "json_schema",
                "name": schema.__name__,
                "strict": True,
                "schema": schema.model_json_schema(),
            }
        },
        truncation="disabled",
    )
    if diagnostics is not None:
        diagnostics.begin(common, max_output_tokens)
    previous_observer = client.response_observer if isinstance(client, BudgetedClient) else None
    if diagnostics is not None and isinstance(client, BudgetedClient):
        client.response_observer = diagnostics.capture_response
    try:
        client.responses.input_tokens.count(**common, timeout=30)
        response = client.responses.create(
            **common, max_output_tokens=max_output_tokens, store=False, timeout=30
        )
        if diagnostics is not None:
            diagnostics.capture_response(
                response
            )  # Fallback for SDK/mock clients without observer.
    finally:
        if isinstance(client, BudgetedClient):
            client.response_observer = previous_observer
    if diagnostics is not None:
        diagnostics.phase = "parsing"
    if response.status != "completed":
        raise ValueError("meta response incomplete or failed")
    parsed = schema.model_validate_json(response.output_text)
    if diagnostics is not None:
        diagnostics.parsed(parsed)
    return parsed
