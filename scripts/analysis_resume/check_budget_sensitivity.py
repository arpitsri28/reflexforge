"""Mocked OpenAI and sandbox integration checks; no real HTTP, Docker or evaluation.

All fake records live in disposable directories explicitly labeled MOCKED. They
are never placed in the study root or included in empirical analysis.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import budget_sensitivity as study
from openai.types.responses import Response

from reflexforge.schema import CommandResult


class MockClient:
    def __init__(self):
        self.responses = SimpleNamespace(
            input_tokens=SimpleNamespace(count=lambda **kw: SimpleNamespace(input_tokens=20)),
            create=self.create,
        )

    def create(self, **kwargs):
        return Response.model_validate(
            {
                "id": "resp_MOCKED_ONLY",
                "created_at": 1.0,
                "model": kwargs["model"],
                "object": "response",
                "output": [],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "status": "completed",
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 10,
                    "total_tokens": 30,
                    "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            }
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class MockSandbox:
    def __init__(self, *args):
        self.deadline = time.monotonic() + 1000
        self.files = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def upload(self, files, **kwargs):
        self.files.update(files)

    def read(self, name):
        return self.files[name]

    def execute(self, *args, **kwargs):
        return CommandResult(
            exit_code=1,
            output='RF_QA {"tests_run":1,"failures":["MOCKED.protected"],"errors":[],"details":[],"successful":false}\n',
        )

    def shell(self, *args, **kwargs):
        return CommandResult(exit_code=0, output="MOCKED")


class LauncherChecks(unittest.TestCase):
    def test_free_preflight_never_constructs_clients(self):
        plan = study.load(study.PLAN)
        with (
            patch("openai.OpenAI", side_effect=AssertionError("no API client in free mode")),
            patch("docker.from_env", side_effect=AssertionError("no Docker in free mode")),
        ):
            info = study.preflight(plan)
        self.assertFalse(info["paid_requests_made"])
        self.assertEqual(info["worker_budget"]["max_tokens"], 40000)
        self.assertEqual(info["bounds"]["scheduled_runs"], 4)

    def test_mocked_full_internal_path_records_cli_shape_and_shared_ledger(self):
        real = study.load(study.PLAN)
        with tempfile.TemporaryDirectory(prefix="reflexforge-MOCKED-sensitivity-") as directory:
            root = Path(directory)
            plan = json.loads(json.dumps(real))
            plan["root"] = str(root)
            for c in plan["copies"]:
                target = root / Path(c["copy"]).relative_to(Path(real["root"]))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(c["source"], target)
                c["copy"] = str(target)
            docker = MagicMock()
            docker.images.get.return_value.id = plan["image_id"]
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "MOCKED-ONLY"}),
                patch("openai.OpenAI", return_value=MockClient()),
                patch("docker.from_env", return_value=docker),
                patch("reflexforge.benchmark.runner.DockerSandbox", MockSandbox),
                patch(
                    "httpx.HTTPTransport.handle_request",
                    side_effect=AssertionError("live HTTP forbidden"),
                ),
            ):
                study.preflight(plan, "train")
                a = study.run_split(plan, "train")
                study.preflight(plan, "dev")
                b = study.run_split(plan, "dev")
            self.assertEqual(a["cells"], 3)
            self.assertEqual(b["cells"], 1)
            self.assertEqual(b["study_ledger"]["api_calls"], 8)
            self.assertEqual(b["study_ledger"]["tokens"], 120)
            runs = []
            for path in root.rglob("experiments.sqlite3"):
                db = sqlite3.connect(path)
                columns = [r[1] for r in db.execute("PRAGMA table_info(runs)")]
                self.assertEqual(
                    columns, ["run_id", "task_id", "split", "synthetic", "status", "result"]
                )
                for rid, data in db.execute("SELECT run_id,result FROM runs"):
                    result = json.loads(data)
                    events = [
                        json.loads(line)
                        for line in (path.parent / "traces" / (rid + ".jsonl"))
                        .read_text()
                        .splitlines()
                    ]
                    self.assertEqual(events[-1]["kind"], "run_end")
                    self.assertEqual(events[-1]["data"], result)
                    self.assertEqual(
                        next(e for e in events if e["kind"] == "worker_start")["data"]["budget"][
                            "max_tokens"
                        ],
                        40000,
                    )
                    self.assertEqual(result["evaluation"], "failed")
                    self.assertEqual(len([e for e in events if e["kind"] == "evaluation"]), 1)
                    runs.append(rid)
                db.close()
            self.assertEqual(len(runs), 4)
            self.assertEqual(len(set(runs)), 4)
            # The disposable fake run used the real worker/evaluator path and is
            # deleted on leaving this context; no fake empirical data persists.


if __name__ == "__main__":
    unittest.main(verbosity=2)
