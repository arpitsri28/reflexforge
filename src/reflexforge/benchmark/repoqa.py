"""RepoBench QA uses the unchanged independent evaluator; no model calls."""

import json
import re
from pathlib import Path
from typing import Any

from reflexforge.benchmark.manifest import (
    Entry,
    digest,
    load_manifest,
    load_specification,
    resolve_entry,
)
from reflexforge.evaluation.evaluator import Evaluator, make_patch
from reflexforge.sandbox.manager import DockerSandbox
from reflexforge.tasks import fixture_files


def regression_summary(result: Any) -> dict[str, Any]:
    line = next(
        (line[6:] for line in result.output.splitlines() if line.startswith("RF_QA ")), None
    )
    if line is None:
        raise ValueError("missing structured regression result")
    data = json.loads(line)
    return {"exit_code": result.exit_code, **data}


def validate_repository(root: Path, entry: Entry, image: str) -> dict[str, Any]:
    manifest = load_manifest(root)
    spec = load_specification(root, manifest)[entry.id]
    task, directory, patch = resolve_entry(root, entry, references=True)
    original = fixture_files(task, directory)
    hidden = (directory / task.hidden_test).read_text()
    mutant = json.loads((root / "benchmark/mutants" / f"{task.id}.json").read_text())
    if digest(mutant) != spec["mutant_hash"] or not set(mutant) <= set(task.editable):
        raise ValueError("invalid private partial-fix overlay")

    def factory(seconds: int, command: int) -> DockerSandbox:
        return DockerSandbox(image, seconds, command)

    evaluator = Evaluator(factory)
    result: dict[str, Any] = {
        "task_id": task.id,
        "suite": "repobench",
        "manifest_hash": manifest.version,
        "source_hash": entry.source_hash,
        "reference_hash": entry.reference_hash,
        "mutant_hash": spec["mutant_hash"],
        "image_id": image,
        "root_cause_category": spec["domain"],
        "meaningful_modules": spec["meaningful_modules"],
        "valid": False,
        "hidden_test_isolation": False,
    }
    try:
        for name, overlay in [("buggy", {}), ("reference", patch), ("partial_fix", mutant)]:
            with factory(120, 30) as box:
                box.upload(original | overlay)
                isolated = box.shell("test ! -e /evaluation/hidden.py").exit_code == 0
                if not isolated or any(
                    "reference" in p or "specification" in p or "hidden" in p for p in original
                ):
                    raise ValueError("private data present in worker snapshot")
                visible = box.shell(task.reproduction)
                count = re.search(r"Ran (\d+) tests? in", visible.output)
                public_count = int(count.group(1)) if count else 0
                result[name] = {
                    "visible_exit": visible.exit_code,
                    "public_tests_run": public_count,
                    "visible_output": visible.output,
                }
            evaluations = [
                regression_summary(
                    evaluator.evaluate(
                        task, original, make_patch(original, overlay, task.editable), hidden
                    )
                )
                for _ in range(2 if name != "partial_fix" else 1)
            ]
            result[name]["regressions"] = evaluations

        def signature(row):
            return {
                k: row[k] for k in ("exit_code", "tests_run", "failures", "errors", "successful")
            }

        before, after, partial = result["buggy"], result["reference"], result["partial_fix"]
        result["reproducible"] = all(
            signature(result[label]["regressions"][0]) == signature(result[label]["regressions"][1])
            for label in ("buggy", "reference")
        )
        result["hidden_test_isolation"] = True
        result["unmodified_rejected"] = all(
            r["exit_code"] != 0 and not r["successful"] for r in before["regressions"]
        )
        result["partial_fix_rejected"] = partial["regressions"][0]["exit_code"] != 0
        result["valid"] = (
            before["visible_exit"] != 0
            and after["visible_exit"] == 0
            and partial["visible_exit"] == 0
            and result["unmodified_rejected"]
            and result["partial_fix_rejected"]
            and result["reproducible"]
            and all(
                result[label]["public_tests_run"] == spec["public_test_count"]
                for label in ("buggy", "reference", "partial_fix")
            )
            and all(
                r["tests_run"] == spec["hidden_test_count"]
                for label in ("buggy", "reference", "partial_fix")
                for r in result[label]["regressions"]
            )
            and all(
                r["exit_code"] == 0 and r["successful"] and not r["failures"] and not r["errors"]
                for r in after["regressions"]
            )
        )
        if not result["valid"]:
            result["error"] = "RepoBench QA contract failed; inspect per-stage outcomes"
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    return result
