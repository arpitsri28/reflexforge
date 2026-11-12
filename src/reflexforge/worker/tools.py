import json
import re
from pathlib import PurePosixPath
from typing import Any

from pydantic import Field

from reflexforge.sandbox.manager import DockerSandbox
from reflexforge.schema import StrictModel
from reflexforge.worker.config import AgentConfig


class PathArgs(StrictModel):
    path: str


class SearchArgs(PathArgs):
    pattern: str = Field(max_length=500)


class EditArgs(PathArgs):
    content: str = Field(max_length=512_000)


class CommandArgs(StrictModel):
    command: str = Field(min_length=1, max_length=8000)


class SkillArgs(StrictModel):
    name: str


ARGUMENTS = {
    "list_dir": PathArgs,
    "read_file": PathArgs,
    "search_code": SearchArgs,
    "edit_file": EditArgs,
    "run_shell": CommandArgs,
    "run_tests": CommandArgs,
    "read_skill": SkillArgs,
}

# This program is executed ONLY in the container; JSON arrives as an argv element.
FILE_TOOL = r"""
import json, pathlib, re, sys
operation, args = sys.argv[1], json.loads(sys.argv[2])
root = pathlib.Path('/workspace').resolve()
p = (root / args['path']).resolve()
if not p.is_relative_to(root):
    raise ValueError('path escapes workspace')
if operation == 'list_dir':
    print('\n'.join(sorted(x.name for x in p.iterdir())))
elif operation == 'read_file':
    if p.stat().st_size > 512000: raise ValueError('file too large')
    print(p.read_text())
elif operation == 'edit_file':
    p.write_text(args['content'])
    print('file updated')
elif operation == 'search_code':
    pattern = re.compile(args['pattern'])
    for f in ([p] if p.is_file() else p.rglob('*')):
        resolved = f.resolve()
        if not resolved.is_relative_to(root) or not f.is_file(): continue
        if f.stat().st_size > 512000: continue
        try: lines = f.read_text().splitlines()
        except (UnicodeError, OSError): continue
        for number, line in enumerate(lines, 1):
            if pattern.search(line): print(f'{f.relative_to(root)}:{number}:{line}')
"""


class WorkerTools:
    def __init__(self, sandbox: DockerSandbox, config: AgentConfig, editable: list[str]) -> None:
        self.sandbox = sandbox
        self.config = config
        self.editable = set(editable)

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": name,
                "description": self.config.tools.descriptions[name],
                "parameters": schema.model_json_schema(),
                "strict": True,
            }
            for name, schema in ARGUMENTS.items()
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ARGUMENTS:
            raise ValueError(f"unknown tool: {name}")
        args = ARGUMENTS[name].model_validate(arguments)
        if isinstance(args, SkillArgs):
            if args.name not in self.config.skills:
                raise ValueError("unknown skill")
            # Even skill retrieval uses the isolated worker environment.
            result = self.sandbox.execute(
                [
                    "python",
                    "-I",
                    "-c",
                    "import sys; print(sys.argv[1])",
                    self.config.skills[args.name],
                ]
            )
        elif isinstance(args, CommandArgs):
            result = self.sandbox.shell(args.command)
        else:
            path = PurePosixPath(args.path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("path must be relative to workspace")
            if isinstance(args, EditArgs) and path.as_posix() not in self.editable:
                raise ValueError("file is not approved for patch export")
            if isinstance(args, SearchArgs):
                re.compile(args.pattern)
            result = self.sandbox.execute(
                ["python", "-I", "-c", FILE_TOOL, name, json.dumps(args.model_dump())]
            )
        return result.model_dump()
