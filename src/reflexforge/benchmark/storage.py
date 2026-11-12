import json
from typing import Any

from reflexforge.meta.state import OptimizationState


class BenchmarkState(OptimizationState):
    def __init__(self, directory):
        super().__init__(directory)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS benchmark_cells (experiment_id TEXT, task_id TEXT, "
                "attempt INTEGER, condition TEXT, status TEXT, result TEXT, "
                "PRIMARY KEY(experiment_id, task_id, attempt, condition))"
            )

    def cells(self, experiment_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM benchmark_cells WHERE experiment_id=? "
                "ORDER BY task_id, attempt, condition",
                (experiment_id,),
            ).fetchall()
        return [
            {**dict(row), "result": json.loads(row["result"]) if row["result"] else None}
            for row in rows
        ]

    def save_cell(
        self,
        experiment_id: str,
        task_id: str,
        attempt: int,
        condition: str,
        status: str,
        result: dict | None = None,
    ) -> None:
        safe = self.trace.sanitize(result)
        with self.connect() as db:
            db.execute(
                "UPDATE benchmark_cells SET status=?, result=? WHERE experiment_id=? AND "
                "task_id=? AND attempt=? AND condition=?",
                (
                    status,
                    json.dumps(safe) if safe else None,
                    experiment_id,
                    task_id,
                    attempt,
                    condition,
                ),
            )
        self.trace.event(
            "benchmark_cell",
            {
                "experiment_id": experiment_id,
                "task_id": task_id,
                "attempt": attempt,
                "condition": condition,
                "status": status,
                "result": safe,
            },
        )

    def recover(self, active_version: str | None = None) -> None:
        super().recover(active_version)
        with self.connect() as db:
            db.execute("UPDATE benchmark_cells SET status='interrupted' WHERE status='running'")

    def experiment(self, experiment_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            raise ValueError("unknown benchmark experiment")
        return {
            **dict(row),
            "settings": json.loads(row["settings"]),
            "cells": self.cells(experiment_id),
        }
