import difflib
from dataclasses import dataclass

from reflexforge.sandbox.manager import SandboxError, SandboxFactory
from reflexforge.schema import CommandResult, Task


@dataclass(frozen=True)
class Patch:
    files: dict[str, str]
    diff: str


def make_patch(original: dict[str, str], changed: dict[str, str], editable: list[str]) -> Patch:
    if not changed.keys() <= set(editable) or not changed.keys() <= original.keys():
        raise ValueError("patch contains unapproved files")
    files = {name: text for name, text in changed.items() if text != original[name]}
    diff = "".join(
        "".join(
            difflib.unified_diff(
                original[name].splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )
        for name, text in sorted(files.items())
    )
    return Patch(files=files, diff=diff)


class Evaluator:
    def __init__(self, factory: SandboxFactory):
        self.factory = factory

    def evaluate(
        self, task: Task, original: dict[str, str], patch: Patch, hidden: str
    ) -> CommandResult:
        # Revalidate: callers cannot use a forged Patch to overwrite tests.
        make_patch(original, patch.files, task.editable)
        with self.factory(task.budget.wall_seconds, task.budget.command_seconds) as box:
            box.upload(original | patch.files)
            box.upload({"hidden.py": hidden}, evaluation=True)
            if task.setup:
                setup = box.shell(task.setup)
                if setup.exit_code:
                    raise SandboxError(f"evaluator setup failed: {setup.output}")
            return box.execute(task.evaluation_command)
