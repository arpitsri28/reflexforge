import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import docker

from reflexforge.benchmark.manifest import (
    Entry,
    Manifest,
    inspect_bank,
    load_manifest,
    resolve_entry,
)
from reflexforge.meta.state import atomic_json
from reflexforge.sandbox.manager import DockerSandbox
from reflexforge.tasks import fixture_files


def validate_fixture(root: Path, entry: Entry, image: str) -> dict[str, Any]:
    if load_manifest(root).format_version == 2:
        from reflexforge.benchmark.repoqa import validate_repository

        return validate_repository(root, entry, image)
    task, directory, patch = resolve_entry(root, entry, references=True)
    original = fixture_files(task, directory)
    hidden = (directory / task.hidden_test).read_text()
    result: dict[str, Any] = {
        "task_id": task.id,
        "source_hash": entry.source_hash,
        "reference_hash": entry.reference_hash,
        "image_id": image,
        "valid": False,
    }
    try:
        for label, files in [("buggy", original), ("reference", original | patch)]:
            with DockerSandbox(image, 90, 20) as box:
                box.upload(files)
                box.upload({"hidden.py": hidden}, evaluation=True)
                visible = box.shell(task.reproduction)
                runs = [box.execute(task.evaluation_command) for _ in range(2)]
                result[label] = {
                    "visible_exit": visible.exit_code,
                    "regression_exits": [r.exit_code for r in runs],
                    "deterministic_output": runs[0].output == runs[1].output,
                    "outputs": [r.output for r in runs],
                }
        before, after = result["buggy"], result["reference"]
        result["valid"] = (
            before["visible_exit"] != 0
            and all(c != 0 for c in before["regression_exits"])
            and after["visible_exit"] == 0
            and after["regression_exits"] == [0, 0]
            and before["deterministic_output"]
            and after["deterministic_output"]
        )
        if not result["valid"]:
            result["error"] = "buggy/reference distinction or deterministic checks failed"
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    return result


def validate_benchmark(
    root: Path,
    manifest: Manifest,
    *,
    workers: int = 2,
    selected: list[str] | None = None,
    artifacts: Path | None = None,
) -> dict[str, Any]:
    inspection = inspect_bank(root, manifest)
    client = docker.from_env(timeout=30)
    try:
        image = client.images.get(os.getenv("REFLEXFORGE_IMAGE", "reflexforge-sandbox:local")).id
    finally:
        client.close()
    directory = (artifacts or root / "artifacts" / "benchmark") / "qa" / manifest.version
    directory.mkdir(parents=True, exist_ok=True)
    entries = [e for e in manifest.entries if selected is None or e.id in selected]
    if not entries or selected is not None and set(selected) != {e.id for e in entries}:
        raise ValueError("unknown or empty fixture selection")
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(validate_fixture, root, entry, image): entry for entry in entries}
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            atomic_json(directory / f"{result['task_id']}.json", result)
            print(f"{result['task_id']}: {'valid' if result['valid'] else 'FAILED'}", flush=True)
    report = {
        **inspection,
        "image_id": image,
        "selected_count": len(entries),
        "valid_count": sum(r["valid"] for r in results),
        "results": sorted(results, key=lambda r: r["task_id"]),
    }
    atomic_json(directory / "validation.json", report)
    return report
