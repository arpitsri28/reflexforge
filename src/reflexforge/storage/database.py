import json
import sqlite3
from pathlib import Path

from reflexforge.schema import RunResult
from reflexforge.storage.traces import Trace


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, split TEXT NOT NULL,
                synthetic INTEGER NOT NULL, status TEXT NOT NULL, result TEXT)""")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def start(self, run_id: str, task_id: str, split: str, synthetic: bool) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, 'running', NULL)",
                (run_id, task_id, split, int(synthetic)),
            )

    def finish(self, result: RunResult, trace: Trace) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status='finished', result=? WHERE run_id=?",
                (json.dumps(trace.sanitize(result.model_dump())), result.run_id),
            )

    def results(self, *, include_synthetic: bool = False) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT result FROM runs WHERE status='finished' AND (synthetic=0 OR ?=1)",
                (int(include_synthetic),),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
