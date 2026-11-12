import json
from pathlib import Path

from reflexforge.schema import Task


def load_tasks(root: Path, split: str | None = None) -> list[tuple[Task, Path]]:
    tasks = []
    ids = set()
    pattern = f"{split}/*/task.json" if split is not None else "*/*/task.json"
    for path in sorted(root.glob(pattern)):
        task = Task.model_validate(json.loads(path.read_text()))
        if task.split != path.parent.parent.name:
            raise ValueError(f"split mismatch: {path}")
        if task.id in ids:
            raise ValueError(f"duplicate task id: {task.id}")
        ids.add(task.id)
        if split is None or task.split == split:
            tasks.append((task, path.parent))
    return tasks


def fixture_files(task: Task, directory: Path) -> dict[str, str]:
    repository = (directory / task.repository).resolve()
    if not repository.is_relative_to(directory.resolve()):
        raise ValueError("repository escapes task directory")
    result = {}
    for path in repository.rglob("*"):
        if path.is_symlink():
            raise ValueError("fixture symlinks are forbidden")
        if path.is_file():
            result[path.relative_to(repository).as_posix()] = path.read_text()
    if not set(task.editable) <= result.keys():
        raise ValueError("editable files missing from fixture")
    return result
