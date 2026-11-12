from pathlib import Path

import pytest

from reflexforge.worker.config import AgentConfig

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return AgentConfig.load(ROOT / "config")


@pytest.fixture(autouse=True)
def forbid_live_llm_http(monkeypatch):
    """SDK tests must explicitly supply MockTransport; Docker uses requests, not httpx."""
    import httpx

    send = httpx.Client.send
    async_send = httpx.AsyncClient.send

    def guarded(client, *args, **kwargs):
        if not isinstance(client._transport, httpx.MockTransport):
            raise AssertionError("Live HTTP/LLM requests are forbidden in the test suite")
        return send(client, *args, **kwargs)

    async def async_guarded(client, *args, **kwargs):
        if not isinstance(client._transport, httpx.MockTransport):
            raise AssertionError("Live HTTP/LLM requests are forbidden in the test suite")
        return await async_send(client, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded)
    monkeypatch.setattr(httpx.AsyncClient, "send", async_guarded)
