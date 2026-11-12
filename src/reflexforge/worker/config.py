import hashlib
import json
from pathlib import Path

import yaml
from pydantic import Field

from reflexforge.schema import Budget, StrictModel

TOOL_NAMES = {
    "list_dir",
    "read_file",
    "search_code",
    "edit_file",
    "run_shell",
    "run_tests",
    "read_skill",
}


class Workflow(StrictModel):
    steps: list[str] = Field(min_length=1)


class ToolConfig(StrictModel):
    descriptions: dict[str, str]


class AgentConfig(StrictModel):
    system_prompt: str = Field(min_length=1)
    workflow: Workflow
    tools: ToolConfig
    params: Budget
    skills: dict[str, str]

    @classmethod
    def load(cls, directory: Path) -> "AgentConfig":
        config = cls(
            system_prompt=(directory / "system_prompt.md").read_text(),
            workflow=Workflow.model_validate(
                yaml.safe_load((directory / "workflow.yaml").read_text())
            ),
            tools=ToolConfig.model_validate(yaml.safe_load((directory / "tools.yaml").read_text())),
            params=Budget.model_validate(yaml.safe_load((directory / "params.yaml").read_text())),
            skills={p.stem: p.read_text() for p in sorted((directory / "skills").glob("*.md"))},
        )
        if set(config.tools.descriptions) != TOOL_NAMES:
            raise ValueError("configuration must describe exactly the approved seven tools")
        return config

    @property
    def version(self) -> str:
        data = json.dumps(self.model_dump(), sort_keys=True).encode()
        return hashlib.sha256(data).hexdigest()

    def prompt(self) -> str:
        return self.system_prompt + "\nWorkflow:\n" + "\n".join(self.workflow.steps)
