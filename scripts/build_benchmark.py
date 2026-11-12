"""Materialize authored fixture data and hash a private benchmark manifest.

Does not execute task code. Existing three fixtures are preserved byte-for-byte.
"""

import json
from pathlib import Path

from benchmark_catalog import CASES

from reflexforge.benchmark.manifest import digest, task_content
from reflexforge.schema import Task

ROOT = Path(__file__).resolve().parents[1]


def split_for(number):
    # Shared exception-taxonomy and context-resource templates stay in training.
    if number in (19, 20):
        return "dev"
    if number in (27, 30):
        return "train"
    return "train" if number <= 20 else "dev" if number <= 31 else "test"


for case in CASES:
    number = case["number"]
    split = split_for(number)
    directory = ROOT / "tasks" / split / f"task_{number:03}"
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in case["files"].items():
        path = directory / "repo" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (directory / "repo" / "test_visible.py").write_text(case["visible"])
    (directory / "hidden.py").write_text(
        "import sys\nsys.path.insert(0, '/workspace')\nprint('REGRESSION_START', flush=True)\n"
        + case["hidden"]
        + "\nprint('REGRESSION_PASS', flush=True)\n"
    )
    task = Task(
        id=directory.name,
        split=split,
        repository="repo",
        issue=case["issue"],
        setup="",
        reproduction="python test_visible.py",
        editable=list(case["files"]),
    )
    (directory / "task.json").write_text(task.model_dump_json(indent=2) + "\n")
    (ROOT / "benchmark" / "references" / f"{task.id}.json").write_text(
        json.dumps(case["reference"], indent=2) + "\n"
    )

legacy = [
    (
        "train",
        "task_001",
        {"solution.py": "def first(items, n):\n    return items[:n]\n"},
        "slice-boundary",
    ),
    (
        "dev",
        "task_002",
        {
            "solution.py": "def paginate(items, page, size):\n    start = (page - 1) * size\n    return items[start:start + size]\n"
        },
        "one-based-page-index",
    ),
    (
        "test",
        "task_003",
        {
            "solution.py": 'def enabled(records):\n    return [r for r in records if r.get("enabled", False)]\n'
        },
        "enabled-record-predicate",
    ),
]
entries = []
for split, task_id, patch, family in legacy:
    (ROOT / "benchmark" / "references" / f"{task_id}.json").write_text(
        json.dumps(patch, indent=2) + "\n"
    )
    entries.append(
        dict(
            id=task_id,
            split=split,
            family=family,
            category=family,
            difficulty="easy",
            affected_modules=1,
            prior_agent_exposure=True,
            coverage=["reported reproduction", "empty input", "boundary behavior"],
        )
    )
for case in CASES:
    entries.append(
        dict(
            id=f"task_{case['number']:03}",
            split=split_for(case["number"]),
            family={
                8: "exception-taxonomy",
                27: "exception-taxonomy",
                14: "context-resource-cleanup",
                30: "context-resource-cleanup",
            }.get(case["number"], case["family"]),
            category=case["category"],
            difficulty=case["difficulty"],
            affected_modules=len(case["reference"]),
            prior_agent_exposure=False,
            coverage=case["coverage"],
        )
    )
for entry in entries:
    path = f"tasks/{entry['split']}/{entry['id']}/task.json"
    task = Task.model_validate(json.loads((ROOT / path).read_text()))
    patch = json.loads((ROOT / "benchmark" / "references" / f"{entry['id']}.json").read_text())
    entry.update(
        task_path=path,
        source_hash=digest(task_content(task, (ROOT / path).parent)),
        reference_hash=digest(patch),
    )
content = {
    "provenance": "project-authored synthetic debugging fixtures",
    "entries": sorted(entries, key=lambda e: e["id"]),
}
(ROOT / "benchmark" / "manifest.json").write_text(
    json.dumps({"format_version": 1, "version": digest(content), **content}, indent=2) + "\n"
)
print("Built benchmark:", len(entries), "tasks; version", digest(content))
