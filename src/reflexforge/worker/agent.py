import json
import math
import os
import time
from typing import Any

import openai

from reflexforge.schema import Budget, RunResult
from reflexforge.storage.traces import Trace
from reflexforge.worker.config import AgentConfig
from reflexforge.worker.tools import WorkerTools

DEFAULT_MODEL = "gpt-5.4-mini"
MIN_OUTPUT_TOKENS = 16


def configured_model() -> str:
    return os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


def effective_budget(config: Budget, task: Budget) -> Budget:
    return Budget.model_validate(
        {k: min(v, task.model_dump()[k]) for k, v in config.model_dump().items()}
    )


def estimate_cost(
    input_tokens: int, output_tokens: int, cached_input_tokens: int = 0
) -> float | None:
    prices = [os.getenv("REFLEXFORGE_INPUT_PRICE"), os.getenv("REFLEXFORGE_OUTPUT_PRICE")]
    if not all(prices):
        return None
    # Without a cache rate, ordinary input pricing gives a conservative estimate.
    values = [float(p) for p in prices]
    values.append(float(os.getenv("REFLEXFORGE_CACHED_INPUT_PRICE") or values[0]))
    if any(p < 0 or not math.isfinite(p) for p in values):
        raise ValueError("token prices must be finite and nonnegative")
    return (
        (input_tokens - cached_input_tokens) * values[0]
        + output_tokens * values[1]
        + cached_input_tokens * values[2]
    ) / 1_000_000


def api_error_details(exc: openai.APIError, phase: str) -> dict[str, Any]:
    # SDK error messages/bodies can echo credentials. Never log them.
    return {
        "phase": phase,
        "type": type(exc).__name__,
        "status_code": getattr(exc, "status_code", None),
    }


class WorkerAgent:
    def __init__(
        self,
        client: Any,
        model: str,
        *,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
    ):
        self.client = client
        self.model = model
        self.temperature, self.reasoning_effort = temperature, reasoning_effort

    def run(
        self,
        issue: str,
        reproduction: str,
        config: AgentConfig,
        tools: WorkerTools,
        budget: Budget,
        trace: Trace,
        result: RunResult,
        reflection_only: bool = False,
    ) -> None:
        items: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": f"Issue: {issue}\nReproduce: {reproduction}\nEditable source: {sorted(tools.editable)}",
            }
        ]
        definitions = tools.definitions()
        deadline = min(time.monotonic() + budget.wall_seconds, tools.sandbox.deadline)
        failures = 0
        result.termination = "step_limit"
        trace.event(
            "worker_start",
            {
                "provider": "openai",
                "model": self.model,
                "sampling": {
                    "temperature": self.temperature,
                    "reasoning_effort": self.reasoning_effort,
                },
                "budget": budget.model_dump(),
                "config": config.model_dump(),
                "input": items,
            },
        )
        for step in range(budget.max_steps):
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                result.termination = "wall_timeout"
                break
            common = dict(
                model=self.model,
                instructions=config.prompt(),
                tools=definitions,
                input=list(items),
                parallel_tool_calls=False,
                truncation="disabled",
            )
            if self.reasoning_effort is not None:
                common["reasoning"] = {"effort": self.reasoning_effort}
            sampling = {"temperature": self.temperature} if self.temperature is not None else {}
            phase = "count_tokens"
            output_limit = 0
            counted_input = 0
            try:
                # Include all history, instructions, and tool schemas in the reservation.
                counted = self.client.responses.input_tokens.count(
                    **common, timeout=max(0.01, min(30, remaining_time))
                )
                counted_input = counted.input_tokens
                remaining = budget.max_tokens - result.input_tokens - result.output_tokens
                output_limit = min(budget.response_tokens, remaining - counted_input)
                if output_limit < MIN_OUTPUT_TOKENS:
                    result.termination = "token_limit"
                    break
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    result.termination = "wall_timeout"
                    break
                phase = "generate"
                response = self.client.responses.create(
                    **common,
                    **sampling,
                    max_output_tokens=output_limit,
                    store=False,
                    include=["reasoning.encrypted_content"],
                    timeout=max(0.01, min(30, remaining_time)),
                )
            except KeyboardInterrupt:
                if phase == "generate":
                    result.usage_incomplete = True
                    result.unconfirmed_tokens += counted_input + output_limit
                raise
            except openai.APIError as exc:
                trace.event("api_error", api_error_details(exc, phase))
                status = getattr(exc, "status_code", None)
                transient = (
                    isinstance(exc, openai.APIConnectionError)
                    or status in (408, 409, 429)
                    or (status is not None and status >= 500)
                )
                # A lost generation response can still have been billed. Fail closed.
                ambiguous = phase == "generate" and (
                    isinstance(exc, openai.APIConnectionError)
                    or status is None
                    or status not in (400, 401, 403, 404, 422, 429)
                )
                if ambiguous:
                    result.usage_incomplete = True
                    result.unconfirmed_tokens += counted_input + output_limit
                failures += 1
                if not transient or ambiguous or failures > budget.retry_limit:
                    result.termination = "api_error"
                    result.failure_category = "api_failure"
                    break
                trace.event("api_retry", {"phase": phase, "attempt": failures})
                time.sleep(min(0.25 * 2 ** (failures - 1), max(0, deadline - time.monotonic())))
                continue
            result.steps = step + 1
            if response.usage is None:
                result.usage_incomplete = True
                result.unconfirmed_tokens += counted_input + output_limit
                result.termination = "missing_usage"
                trace.event("api_error", {"phase": "generate", "type": "MissingUsage"})
                break
            usage = response.usage
            result.input_tokens += usage.input_tokens
            result.output_tokens += usage.output_tokens
            result.cached_input_tokens += (
                getattr(usage.input_tokens_details, "cached_tokens", 0) or 0
            )
            result.reasoning_tokens += (
                getattr(usage.output_tokens_details, "reasoning_tokens", 0) or 0
            )
            content = [item.model_dump(mode="json", exclude_none=True) for item in response.output]
            trace.event(
                "model_response",
                {
                    "provider": "openai",
                    "response_id": response.id,
                    "model": response.model,
                    # Keep opaque reasoning state in memory for replay, not in trace files.
                    "output": [
                        {k: v for k, v in item.items() if k != "encrypted_content"}
                        for item in content
                    ],
                    "status": response.status,
                    "usage": usage.model_dump(mode="json"),
                },
            )
            items.extend(content)
            if result.input_tokens + result.output_tokens > budget.max_tokens:
                result.termination = "token_limit"
                break
            # Truncated/incomplete arguments must never cause execution of a partial action.
            if response.status != "completed":
                result.termination = f"model_{response.status}"
                break
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                refused = any(
                    item.get("type") == "message"
                    and any(part.get("type") == "refusal" for part in item.get("content", []))
                    for item in content
                )
                if (
                    reflection_only
                    and not refused
                    and result.reflection_retries == 0
                    and step + 1 < budget.max_steps
                    and result.tool_calls < budget.max_steps
                ):
                    tools.sandbox.check()
                    result.tool_calls += 1
                    feedback = tools.call("run_tests", {"command": reproduction})
                    trace.event("reflection_visible_check", feedback)
                    if feedback.get("exit_code", 1) != 0:
                        result.reflection_retries += 1
                        items.append(
                            {
                                "role": "user",
                                "content": "Your visible reproduction still fails. Reflect on this visible feedback, "
                                "diagnose the cause, repair it, and validate again within your remaining budget. "
                                "No hidden evaluator feedback is available.\n"
                                + json.dumps(feedback),
                            }
                        )
                        continue
                result.termination = "refused" if refused else "completed"
                break
            # Provider is asked for one call at a time; also bound unexpected multi-call output.
            if result.tool_calls + len(calls) > budget.max_steps:
                result.termination = "tool_call_limit"
                break
            for call in calls:
                if time.monotonic() >= deadline:
                    result.termination = "wall_timeout"
                    return
                tools.sandbox.check()
                result.tool_calls += 1
                trace.event(
                    "tool_call",
                    {
                        "id": call.id,
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                )
                try:
                    arguments = json.loads(call.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("function arguments must be a JSON object")
                    value = tools.call(call.name, arguments)
                    is_error = value.get("exit_code", 0) != 0
                except (ValueError, KeyError) as exc:
                    value, is_error = {"error": str(exc)}, True
                trace.event(
                    "tool_result",
                    {
                        "call_id": call.call_id,
                        "name": call.name,
                        "result": value,
                        "is_error": is_error,
                    },
                )
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps({**value, "is_error": is_error}),
                    }
                )
        result.cost_usd = (
            None
            if result.usage_incomplete
            else estimate_cost(
                result.input_tokens, result.output_tokens, result.cached_input_tokens
            )
        )
