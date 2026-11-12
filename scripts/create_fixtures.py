"""Create deterministic fixtures as data; never imports or executes task code."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    (
        "train",
        "Return exactly the first n items; first([1, 2, 3], 2) should return [1, 2].",
        "def first(items, n):\n    return items[:n + 1]\n",
        "assert first([1, 2, 3], 2) == [1, 2]",
        "assert m.first([1, 2, 3], 2) == [1, 2]\nassert m.first([1], 0) == []\nassert m.first([], 3) == []",
    ),
    (
        "dev",
        "Pagination is one-indexed. Page 1 with size 2 should return the first two items.",
        "def paginate(items, page, size):\n    start = page * size\n    return items[start:start + size]\n",
        "assert paginate([1, 2, 3, 4], 1, 2) == [1, 2]",
        "assert m.paginate([1, 2, 3, 4], 1, 2) == [1, 2]\nassert m.paginate([1, 2, 3], 2, 2) == [3]\nassert m.paginate([], 1, 5) == []",
    ),
    (
        "test",
        "Filter enabled records; disabled records must be omitted and order preserved.",
        'def enabled(records):\n    return [r for r in records if "enabled" in r]\n',
        'assert enabled([{"enabled": False}]) == []',
        'assert m.enabled([{"enabled": False}, {"enabled": True}, {}]) == [{"enabled": True}]\nassert m.enabled([]) == []\nassert m.enabled([{"enabled": True, "id": 1}, {"enabled": True, "id": 2}]) == [{"enabled": True, "id": 1}, {"enabled": True, "id": 2}]',
    ),
]
for index, (split, issue, source, visible, hidden) in enumerate(CASES, 1):
    task_id = f"task_{index:03}"
    directory = ROOT / "tasks" / split / task_id
    (directory / "repo").mkdir(parents=True, exist_ok=True)
    (directory / "repo" / "solution.py").write_text(source)
    function = ["first", "paginate", "enabled"][index - 1]
    (directory / "repo" / "test_visible.py").write_text(
        f"from solution import {function}\n{visible}\n"
    )
    (directory / "hidden.py").write_text(
        "import importlib.util\nfrom pathlib import Path\n"
        'assert Path("/evaluation/hidden.py").is_file()\n'
        'spec = importlib.util.spec_from_file_location("solution", "/workspace/solution.py")\n'
        "m = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\n" + hidden + "\n"
    )
    task = dict(
        id=task_id,
        repository="repo",
        issue=issue,
        setup="",
        reproduction="python test_visible.py",
        hidden_test="hidden.py",
        runtime="python3.11",
        split=split,
        editable=["solution.py"],
    )
    (directory / "task.json").write_text(json.dumps(task, indent=2) + "\n")
