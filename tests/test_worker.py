import json
import time
from unittest.mock import MagicMock

import httpx
import openai
import pytest
from openai.types.responses import Response

from reflexforge.schema import Budget, RunResult
from reflexforge.storage.traces import Trace
from reflexforge.worker.agent import (
    DEFAULT_MODEL,
    WorkerAgent,
    configured_model,
    effective_budget,
    estimate_cost,
)
from reflexforge.worker.tools import WorkerTools


def function_call(name="read_file", arguments=None, call_id="call_1", item_id="fc_1"):
    return {
        "type": "function_call",
        "id": item_id,
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps({"path": "solution.py"} if arguments is None else arguments),
        "status": "completed",
    }


def response(
    output,
    status="completed",
    *,
    input_tokens=20,
    output_tokens=10,
    cached_tokens=0,
    reasoning_tokens=0,
):
    return Response.model_validate(
        {
            "id": "resp_test",
            "created_at": 1.0,
            "model": "unit-model",
            "object": "response",
            "output": output,
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
            "status": status,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "input_tokens_details": {"cached_tokens": cached_tokens, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
            },
        }
    )


def harness(tmp_path, config):
    box = MagicMock()
    box.deadline = time.monotonic() + 100
    box.execute.return_value.model_dump.return_value = {"exit_code": 0, "output": "source"}
    client = MagicMock()
    client.responses.input_tokens.count.return_value.input_tokens = 20
    tools = WorkerTools(box, config, ["solution.py"])
    trace = Trace(tmp_path / "trace.jsonl", "run")
    result = RunResult(
        run_id="run",
        task_id="task_001",
        config_version=config.version,
        model="test",
        termination="starting",
    )
    return box, client, tools, trace, result


def run(client, config, tools, trace, result, **limits):
    WorkerAgent(client, "unit-model").run(
        "fix", "python test_visible.py", config, tools, Budget(**limits), trace, result
    )


def test_function_protocol_uses_call_id_not_item_id(tmp_path, config):
    box, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.side_effect = [response([function_call()]), response([])]
    run(client, config, tools, trace, result)
    assert result.termination == "completed"
    assert (result.steps, result.tool_calls, result.input_tokens, result.output_tokens) == (
        2,
        1,
        40,
        20,
    )
    sent = client.responses.create.call_args.kwargs["input"]
    assert sent[1]["id"] == "fc_1"
    assert sent[2]["type"] == "function_call_output"
    assert sent[2]["call_id"] == "call_1"
    assert json.loads(sent[2]["output"])["is_error"] is False
    assert box.execute.call_args.args[0][-2] == "read_file"
    assert "tool_result" in trace.path.read_text()


def test_multi_turn_multiple_calls_and_reasoning_state(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    reasoning = {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [],
        "encrypted_content": "opaque-state",
    }
    client.responses.create.side_effect = [
        response(
            [reasoning, function_call(), function_call("list_dir", {"path": "."}, "call_2", "fc_2")]
        ),
        response([function_call("read_skill", {"name": "debugging"}, "call_3", "fc_3")]),
        response([]),
    ]
    run(client, config, tools, trace, result)
    assert result.tool_calls == 3 and result.steps == 3
    sent = client.responses.create.call_args.kwargs["input"]
    assert sent[1]["encrypted_content"] == "opaque-state"
    assert [item["call_id"] for item in sent if item.get("type") == "function_call_output"] == [
        "call_1",
        "call_2",
        "call_3",
    ]
    assert "opaque-state" not in trace.path.read_text()
    for call in client.responses.create.call_args_list:
        assert call.kwargs["store"] is False
        assert call.kwargs["instructions"] == config.prompt()
        assert call.kwargs["parallel_tool_calls"] is False


@pytest.mark.parametrize("arguments", ["invalid{", "[]", "null", '"string"'])
def test_malformed_arguments_return_matching_error_without_execution(tmp_path, config, arguments):
    box, client, tools, trace, result = harness(tmp_path, config)
    call = function_call()
    call["arguments"] = arguments
    client.responses.create.side_effect = [response([call]), response([])]
    run(client, config, tools, trace, result)
    sent = client.responses.create.call_args.kwargs["input"]
    assert sent[2]["call_id"] == "call_1"
    assert json.loads(sent[2]["output"])["is_error"]
    box.execute.assert_not_called()


def test_invalid_tool_is_error_output(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.side_effect = [
        response([function_call("delete_database", {})]),
        response([]),
    ]
    run(client, config, tools, trace, result)
    assert json.loads(client.responses.create.call_args.kwargs["input"][2]["output"])["is_error"]


def test_shell_failure_returned_to_model(tmp_path, config):
    box, client, tools, trace, result = harness(tmp_path, config)
    box.shell.return_value.model_dump.return_value = {"exit_code": 1, "output": "AssertionError"}
    client.responses.create.side_effect = [
        response([function_call("run_tests", {"command": "python test_visible.py"})]),
        response([]),
    ]
    run(client, config, tools, trace, result)
    output = json.loads(client.responses.create.call_args.kwargs["input"][2]["output"])
    assert output["is_error"] and output["exit_code"] == 1


def test_token_reservation_and_minimum_output(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.input_tokens.count.return_value.input_tokens = 1010
    run(client, config, tools, trace, result, max_tokens=1024)
    assert result.termination == "token_limit"
    client.responses.create.assert_not_called()


def test_token_cap_counts_cumulative_input_and_output(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.input_tokens.count.return_value.input_tokens = 600
    client.responses.create.return_value = response(
        [function_call()], input_tokens=600, output_tokens=100
    )
    run(client, config, tools, trace, result, max_tokens=1024)
    assert result.termination == "token_limit"
    assert client.responses.create.call_count == 1
    assert client.responses.create.call_args.kwargs["max_output_tokens"] == 424


def test_infinite_calls_stop_at_step_budget(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.side_effect = [
        response([function_call(call_id=f"call_{i}", item_id=f"fc_{i}")]) for i in range(2)
    ]
    run(client, config, tools, trace, result, max_steps=2)
    assert result.termination == "step_limit"
    assert result.tool_calls == 2
    assert client.responses.create.call_count == 2


def test_excessive_parallel_calls_stopped(tmp_path, config):
    box, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.return_value = response(
        [function_call(call_id=f"call_{i}", item_id=f"fc_{i}") for i in range(3)]
    )
    run(client, config, tools, trace, result, max_steps=2)
    assert result.termination == "tool_call_limit"
    box.execute.assert_not_called()


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
def test_noncompleted_response_never_executes_tools(tmp_path, config, status):
    box, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.return_value = response([function_call()], status)
    run(client, config, tools, trace, result)
    assert result.termination == f"model_{status}"
    box.execute.assert_not_called()


def test_wall_timeout_prevents_api_calls(tmp_path, config):
    box, client, tools, trace, result = harness(tmp_path, config)
    box.deadline = time.monotonic() - 1
    run(client, config, tools, trace, result)
    assert result.termination == "wall_timeout"
    client.responses.input_tokens.count.assert_not_called()


def test_count_api_retries_bounded(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.input_tokens.count.side_effect = openai.APIConnectionError(
        request=httpx.Request("POST", "https://example.invalid")
    )
    run(client, config, tools, trace, result, retry_limit=1)
    assert result.termination == "api_error"
    assert not result.usage_incomplete
    assert client.responses.input_tokens.count.call_count == 2
    client.responses.create.assert_not_called()


def test_generation_rate_limit_retries(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.side_effect = [
        openai.RateLimitError(
            "try later",
            response=httpx.Response(429, request=httpx.Request("POST", "https://example.invalid")),
            body=None,
        ),
        response([]),
    ]
    run(client, config, tools, trace, result, retry_limit=1)
    assert result.termination == "completed" and not result.usage_incomplete
    assert client.responses.create.call_count == 2


@pytest.mark.parametrize("error_type", ["timeout", "server_error"])
def test_ambiguous_generation_stops_without_retry_or_false_cost(tmp_path, config, error_type):
    _, client, tools, trace, result = harness(tmp_path, config)
    request = httpx.Request("POST", "https://example.invalid")
    error = (
        openai.APITimeoutError(request=request)
        if error_type == "timeout"
        else openai.InternalServerError(
            "server failed", response=httpx.Response(500, request=request), body=None
        )
    )
    client.responses.create.side_effect = error
    run(client, config, tools, trace, result)
    assert result.termination == "api_error" and result.usage_incomplete
    assert result.unconfirmed_tokens == 20 + 2048
    assert result.cost_usd is None
    assert client.responses.create.call_count == 1


def test_auth_error_not_retried_and_key_not_logged(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.side_effect = openai.AuthenticationError(
        "Incorrect API key sk-proj-should-never-be-logged",
        response=httpx.Response(401, request=httpx.Request("POST", "https://example.invalid")),
        body=None,
    )
    run(client, config, tools, trace, result)
    assert result.termination == "api_error" and not result.usage_incomplete
    assert client.responses.create.call_count == 1
    assert "sk-proj-" not in trace.path.read_text()
    assert "AuthenticationError" in trace.path.read_text()


def test_missing_usage_stops(tmp_path, config):
    box, client, tools, trace, result = harness(tmp_path, config)
    reply = response([function_call()])
    reply.usage = None
    client.responses.create.return_value = reply
    run(client, config, tools, trace, result)
    assert result.termination == "missing_usage" and result.usage_incomplete
    assert result.cost_usd is None
    box.execute.assert_not_called()


def test_usage_counts_cache_and_reasoning_without_double_count(tmp_path, config, monkeypatch):
    monkeypatch.setenv("REFLEXFORGE_INPUT_PRICE", "1")
    monkeypatch.setenv("REFLEXFORGE_OUTPUT_PRICE", "4")
    monkeypatch.setenv("REFLEXFORGE_CACHED_INPUT_PRICE", "0.1")
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.return_value = response(
        [], input_tokens=100, output_tokens=50, cached_tokens=40, reasoning_tokens=20
    )
    run(client, config, tools, trace, result)
    assert (
        result.input_tokens,
        result.output_tokens,
        result.cached_input_tokens,
        result.reasoning_tokens,
    ) == (100, 50, 40, 20)
    assert result.cost_usd == pytest.approx(0.000264)


def test_budget_pricing_and_model_default(monkeypatch):
    assert effective_budget(Budget(max_steps=5), Budget(max_steps=3)).max_steps == 3
    for name in [
        "REFLEXFORGE_INPUT_PRICE",
        "REFLEXFORGE_OUTPUT_PRICE",
        "REFLEXFORGE_CACHED_INPUT_PRICE",
        "OPENAI_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)
    assert configured_model() == DEFAULT_MODEL
    monkeypatch.setenv("OPENAI_MODEL", "custom-model")
    assert configured_model() == "custom-model"
    assert estimate_cost(1000, 1000) is None
    monkeypatch.setenv("REFLEXFORGE_INPUT_PRICE", "3")
    monkeypatch.setenv("REFLEXFORGE_OUTPUT_PRICE", "15")
    assert estimate_cost(1000, 1000, 500) == pytest.approx(0.018)
    monkeypatch.setenv("REFLEXFORGE_CACHED_INPUT_PRICE", "nan")
    with pytest.raises(ValueError):
        estimate_cost(1, 1)


def test_sdk_serializes_three_turn_exchange_with_http_mock(tmp_path, config):
    """Exercise the real SDK's parsing and request serialization without live requests."""
    _, _, tools, trace, result = harness(tmp_path, config)
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path == "/v1/responses/input_tokens":
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 30})
        assert request.url.path == "/v1/responses"
        step = sum(path == "/v1/responses" for path, _ in requests)
        output = [function_call(call_id=f"call_{step}", item_id=f"fc_{step}")] if step <= 2 else []
        reply = response(output, input_tokens=30)
        reply.id = f"resp_{step}"
        return httpx.Response(200, json=reply.model_dump(mode="json"))

    with openai.OpenAI(
        api_key="unit-test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        run(client, config, tools, trace, result)
    assert result.termination == "completed" and result.steps == 3
    turns = [payload for path, payload in requests if path == "/v1/responses"]
    counts = [payload for path, payload in requests if path == "/v1/responses/input_tokens"]
    assert len(turns) == 3 and len(counts) == 3
    assert turns[0]["input"] == counts[0]["input"]
    assert [
        item["call_id"] for item in turns[2]["input"] if item.get("type") == "function_call_output"
    ] == ["call_1", "call_2"]
    assert turns[0]["store"] is False
    assert len(turns[0]["tools"]) == 7
    for tool in turns[0]["tools"]:
        assert tool["type"] == "function" and tool["strict"]
        assert tool["parameters"]["additionalProperties"] is False
        assert set(tool["parameters"]["required"]) == set(tool["parameters"]["properties"])


def test_refusal_terminates(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.return_value = response(
        [
            {
                "type": "message",
                "id": "msg_refusal",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "Unable to complete this request."}],
            }
        ]
    )
    run(client, config, tools, trace, result)
    assert result.termination == "refused"
    assert result.tool_calls == 0


def test_actual_usage_over_budget_stops_further_calls(tmp_path, config):
    box, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.return_value = response(
        [function_call()], input_tokens=1000, output_tokens=100
    )
    run(client, config, tools, trace, result, max_tokens=1024)
    assert result.termination == "token_limit"
    assert result.input_tokens + result.output_tokens == 1100
    assert client.responses.create.call_count == 1
    box.execute.assert_not_called()


def test_interrupted_generation_has_unknown_usage(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run(client, config, tools, trace, result)
    assert result.usage_incomplete and result.unconfirmed_tokens == 2068


def test_reflection_condition_retries_visible_failure_with_shared_budget(tmp_path, config):
    box, client, tools, trace, result = harness(tmp_path, config)
    box.shell.return_value.model_dump.return_value = {"exit_code": 1, "output": "VISIBLE-FAILURE"}
    client.responses.create.side_effect = [response([]), response([])]
    WorkerAgent(client, "unit-model").run(
        "fix",
        "python test_visible.py",
        config,
        tools,
        Budget(max_steps=2),
        trace,
        result,
        reflection_only=True,
    )
    assert result.reflection_retries == 1 and result.steps == 2
    assert result.input_tokens == 40 and result.output_tokens == 20
    assert "VISIBLE-FAILURE" in client.responses.create.call_args.kwargs["input"][-1]["content"]
    assert "/evaluation/" not in str(client.responses.create.call_args.kwargs["input"])
    box.shell.assert_called_once_with("python test_visible.py")


def test_static_condition_does_not_add_controller_reflection(tmp_path, config):
    box, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.return_value = response([])
    run(client, config, tools, trace, result)
    assert result.reflection_retries == 0 and client.responses.create.call_count == 1
    box.shell.assert_not_called()


def test_explicit_sampling_reaches_generation_and_matching_token_count(tmp_path, config):
    _, client, tools, trace, result = harness(tmp_path, config)
    client.responses.create.return_value = response([])
    WorkerAgent(client, "unit-model", temperature=0.0, reasoning_effort="none").run(
        "fix", "python test_visible.py", config, tools, Budget(), trace, result
    )
    assert client.responses.create.call_args.kwargs["temperature"] == 0.0
    assert client.responses.create.call_args.kwargs["reasoning"] == {"effort": "none"}
    assert "temperature" not in client.responses.input_tokens.count.call_args.kwargs
    assert client.responses.input_tokens.count.call_args.kwargs["reasoning"] == {"effort": "none"}
