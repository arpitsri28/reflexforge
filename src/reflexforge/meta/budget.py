"""Durable reservations surround every API request, including token-count requests."""

import json
import uuid
from types import SimpleNamespace
from typing import Any

from reflexforge.meta.schemas import OptimizationSettings
from reflexforge.meta.state import OptimizationState


class BudgetExceeded(RuntimeError):
    pass


class UsageLedger:
    def __init__(
        self, state: OptimizationState, experiment_id: str, settings: OptimizationSettings
    ):
        self.state, self.experiment_id, self.settings = state, experiment_id, settings

    def summary(self) -> dict[str, Any]:
        with self.state.connect() as db:
            rows = db.execute(
                "SELECT * FROM api_usage WHERE experiment_id=?", (self.experiment_id,)
            ).fetchall()
        return {
            "api_calls": sum(r["calls"] for r in rows),
            "tokens": sum(r["tokens"] for r in rows),
            "usd_upper_bound": (
                sum(r["usd"] for r in rows)
                if rows and all(r["usd"] is not None for r in rows)
                else None
            ),
            "uncertain": any(r["state"] in {"reserved", "unknown", "overrun"} for r in rows),
        }

    def reserve(self, role: str, model: str, tokens: int, usd: float | None) -> str:
        ticket = uuid.uuid4().hex
        with self.state.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT * FROM api_usage WHERE experiment_id=?", (self.experiment_id,)
            ).fetchall()
            if any(r["state"] in {"reserved", "unknown", "overrun"} for r in rows):
                raise BudgetExceeded("unresolved or uncertain API usage; no further calls allowed")
            if sum(r["calls"] for r in rows) + 1 > self.settings.max_api_calls:
                raise BudgetExceeded("overall API call limit reached")
            if sum(r["tokens"] for r in rows) + tokens > self.settings.max_tokens:
                raise BudgetExceeded("overall token limit reached")
            if self.settings.max_usd is not None:
                if usd is None or any(r["usd"] is None for r in rows):
                    raise BudgetExceeded("USD cap cannot be enforced without complete pricing")
                if sum(r["usd"] for r in rows) + usd > self.settings.max_usd:
                    raise BudgetExceeded("overall USD cap reached")
            db.execute(
                "INSERT INTO api_usage VALUES (?, ?, ?, ?, ?, 1, ?, ?, NULL)",
                (ticket, self.experiment_id, role, model, "reserved", tokens, usd),
            )
        return ticket

    def finish(
        self, ticket: str, state: str, usage: Any = None, prices: tuple[float, float] | None = None
    ) -> None:
        with self.state.connect() as db:
            row = db.execute("SELECT * FROM api_usage WHERE id=?", (ticket,)).fetchone()
            tokens, usd = row["tokens"], row["usd"]
            actual = None
            if usage is not None:
                actual = usage.model_dump(mode="json")
                measured = usage.input_tokens + usage.output_tokens
                measured_usd = (
                    None
                    if prices is None
                    else (usage.input_tokens * prices[0] + usage.output_tokens * prices[1]) / 1e6
                )
                if measured > tokens or (usd is not None and measured_usd > usd + 1e-12):
                    state = "overrun"
                tokens, usd = measured, measured_usd
            db.execute(
                "UPDATE api_usage SET state=?, tokens=?, usd=?, actual_usage=? WHERE id=?",
                (state, tokens, usd, json.dumps(actual), ticket),
            )
        self.state.trace.event(
            "api_usage",
            {
                "ticket": ticket,
                "role": row["role"],
                "model": row["model"],
                "state": state,
                "tokens": tokens,
                "usd_upper_bound": usd,
                "usage": actual,
            },
        )
        if state == "overrun":
            raise BudgetExceeded("API usage exceeded its reservation; experiment stopped")


class BudgetedClient:
    """Small SDK-compatible adapter used by both existing worker and meta stages."""

    def __init__(
        self,
        client: Any,
        ledger: UsageLedger,
        role: str,
        model: str,
        prices: tuple[float, float] | None,
    ):
        self.client, self.ledger, self.role, self.model, self.prices = (
            client,
            ledger,
            role,
            model,
            prices,
        )
        self.pending: tuple[str, int] | None = None
        self.response_observer = None
        self.responses = SimpleNamespace(
            input_tokens=SimpleNamespace(count=self.count), create=self.create
        )

    @staticmethod
    def fingerprint(kwargs: dict[str, Any]) -> str:
        ignored = {
            "timeout",
            "max_output_tokens",
            "store",
            "include",
            "service_tier",
            "temperature",
        }
        return json.dumps({k: v for k, v in kwargs.items() if k not in ignored}, sort_keys=True)

    def count(self, **kwargs: Any) -> Any:
        if kwargs.get("model") != self.model:
            raise ValueError("model selection changed during controlled evaluation")
        ticket = self.ledger.reserve(self.role, self.model, 0, 0.0)
        self.pending = None
        try:
            response = self.client.responses.input_tokens.count(**kwargs)
        except BaseException:
            self.ledger.finish(ticket, "finished")  # Counting cannot generate billed output.
            raise
        self.ledger.finish(ticket, "finished")
        self.pending = self.fingerprint(kwargs), response.input_tokens
        return response

    def create(self, **kwargs: Any) -> Any:
        if self.pending is None or self.pending[0] != self.fingerprint(kwargs):
            raise BudgetExceeded("a matching input-token count is required before generation")
        count = self.pending[1]
        self.pending = None
        maximum = kwargs["max_output_tokens"]
        usd = (
            None
            if self.prices is None
            else (count * self.prices[0] + maximum * self.prices[1]) / 1e6
        )
        ticket = self.ledger.reserve(self.role, self.model, count + maximum, usd)
        try:
            response = self.client.responses.create(
                **{**kwargs, "store": False, "service_tier": "default"}
            )
        except BaseException:
            # Retain full reservation; even interruption or a lost response may have billed.
            self.ledger.finish(ticket, "unknown")
            raise
        capture_error = None
        if self.response_observer is not None:
            try:
                self.response_observer(response)
            except BaseException as exc:
                capture_error = exc
        if response.usage is None:
            self.ledger.finish(ticket, "unknown")
            raise BudgetExceeded("generation returned no usage; no further calls allowed")
        self.ledger.finish(ticket, "finished", response.usage, self.prices)
        if capture_error is not None:
            raise capture_error  # Account for the billed response, but never bypass capture failure.
        return response
