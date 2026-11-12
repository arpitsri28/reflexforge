import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from reflexforge.storage.traces import Trace


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as file:
        json.dump(value, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


@contextmanager
def exclusive_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "another optimization or rollback owns this configuration store"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


class OptimizationState:
    """Separate history from worker runs, with explicit synthetic provenance."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.path = directory / "optimization.sqlite3"
        self.trace = Trace(directory / "audit.jsonl", "optimization")
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS experiments "
                "(id TEXT PRIMARY KEY, synthetic INTEGER, settings TEXT, status TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS iterations "
                "(id TEXT PRIMARY KEY, experiment_id TEXT, number INTEGER, status TEXT, data TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS api_usage "
                "(id TEXT PRIMARY KEY, experiment_id TEXT, role TEXT, model TEXT, "
                "state TEXT, calls INTEGER, tokens INTEGER, usd REAL, actual_usage TEXT)"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(
        self, iteration_id: str, experiment_id: str, number: int, status: str, data: dict[str, Any]
    ) -> None:
        safe = self.trace.sanitize(data)
        with self.connect() as db:
            db.execute(
                "INSERT INTO iterations VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, data=excluded.data",
                (iteration_id, experiment_id, number, status, json.dumps(safe)),
            )
        self.trace.event("iteration", {"id": iteration_id, "status": status, "data": safe})

    def recover(self, active_version: str | None = None) -> None:
        # Never replay an interrupted paid request or silently resume uncertain spend.
        with self.connect() as db:
            rows = db.execute("SELECT id, data FROM iterations WHERE status='running'").fetchall()
            for row in rows:
                data = json.loads(row["data"])
                accepted = (
                    active_version is not None
                    and data.get("candidate") == active_version
                    and data.get("decision", {}).get("accepted") is True
                )
                data["recovered"] = True
                db.execute(
                    "UPDATE iterations SET status=?, data=? WHERE id=?",
                    ("accepted" if accepted else "interrupted", json.dumps(data), row["id"]),
                )
            db.execute("UPDATE experiments SET status='interrupted' WHERE status='running'")
            db.execute("UPDATE api_usage SET state='unknown' WHERE state='reserved'")

    def iterations(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT i.*, e.synthetic FROM iterations i JOIN experiments e "
                "ON e.id=i.experiment_id ORDER BY i.rowid"
            ).fetchall()
        return [{**dict(row), "data": json.loads(row["data"])} for row in rows]

    def rejected_feedback(self) -> list[dict[str, str]]:
        # Deliberately omit evaluation metrics, task ids, traces, and proposal content.
        feedback = []
        for row in self.iterations():
            if row["status"] in {"rejected", "inconclusive", "invalid"}:
                proposal = row["data"].get("proposal", {})
                feedback.append(
                    {"hypothesis": proposal.get("hypothesis", ""), "outcome": row["status"]}
                )
        return feedback[-10:]
