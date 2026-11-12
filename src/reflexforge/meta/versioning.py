import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from reflexforge.meta.schemas import Proposal
from reflexforge.meta.state import atomic_json
from reflexforge.worker.config import AgentConfig


def validate_tree(directory: Path) -> None:
    if directory.is_symlink():
        raise ValueError("configuration symlinks are forbidden")
    for parent in directory.parents:
        if parent.is_symlink():
            raise ValueError("configuration parent symlinks are forbidden")
    allowed = {"system_prompt.md", "workflow.yaml", "tools.yaml", "params.yaml"}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("configuration symlinks are forbidden")
        name = path.relative_to(directory).as_posix()
        if path.is_dir():
            if name != "skills":
                raise ValueError("unexpected configuration directory")
        elif not path.is_file() or (
            name not in allowed and not re.fullmatch(r"skills/[A-Za-z0-9_-]+\.md", name)
        ):
            raise ValueError("unexpected configuration file")
        elif path.stat().st_size > 64000:
            raise ValueError("configuration file exceeds size limit")
    AgentConfig.load(directory)


def candidate_snapshot(source: Path, destination: Path, proposal: Proposal) -> AgentConfig:
    validate_tree(source)
    targets = {
        "config/system_prompt.md": "modify_prompt",
        "config/workflow.yaml": "modify_workflow",
    }
    expected = targets.get(proposal.target_file)
    if re.fullmatch(r"config/skills/[A-Za-z0-9_-]+\.md", proposal.target_file):
        expected = "upsert_skill"
    if expected != proposal.change_type:
        raise ValueError("unauthorized proposal target or change type")
    if destination.exists() or destination.is_symlink():
        raise ValueError("candidate destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in [destination.parent, *destination.parents]):
        raise ValueError("candidate parent symlinks are forbidden")
    shutil.copytree(source, destination)
    target = destination / proposal.target_file.removeprefix("config/")
    target.parent.mkdir(exist_ok=True)
    target.write_text(proposal.proposed_content)
    validate_tree(destination)
    incumbent, candidate = AgentConfig.load(source), AgentConfig.load(destination)
    if candidate.params != incumbent.params or candidate.tools != incumbent.tools:
        raise ValueError("execution parameters and tool permissions must remain fixed")
    if candidate.version == incumbent.version:
        raise ValueError("proposal does not change configuration")
    return candidate


class VersionStore:
    """Dedicated Git repo and atomic active pointer; never touches the developer checkout."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.repo = directory / "config-git"
        self.pointer = directory / "active.json"
        self.repo.mkdir(parents=True, exist_ok=True)
        if not (self.repo / ".git").exists():
            self.git("init", "-q")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        ).stdout.strip()

    def active(self) -> tuple[str, Path] | None:
        if not self.pointer.exists():
            return None
        version = json.loads(self.pointer.read_text())["version"]
        path = self.snapshot(version)
        if AgentConfig.load(path).version != version:
            raise ValueError("active configuration snapshot has been modified")
        return version, path

    def snapshot(self, version: str) -> Path:
        if not re.fullmatch("[0-9a-f]{64}", version):
            raise ValueError("invalid configuration version")
        path = self.repo / "snapshots" / version
        if not (self.repo / "metadata" / f"{version}.json").is_file():
            raise ValueError("unknown accepted configuration version")
        validate_tree(path)
        return path

    def commit(self, source: Path, metadata: dict[str, Any], expected: str | None) -> str:
        validate_tree(source)
        current = self.active()
        if (current[0] if current else None) != expected:
            raise RuntimeError("active version changed during evaluation")
        version = AgentConfig.load(source).version
        target = self.repo / "snapshots" / version
        record = self.repo / "metadata" / f"{version}.json"
        if not record.exists():
            if target.exists():
                shutil.rmtree(target)  # An unpublished snapshot left by interruption.
            target.parent.mkdir(exist_ok=True)
            shutil.copytree(source, target)
            record.parent.mkdir(exist_ok=True)
            atomic_json(record, {**metadata, "version": version, "parent": expected})
        if AgentConfig.load(target).version != version:
            raise ValueError("accepted snapshot content hash mismatch")
        try:
            self.git("cat-file", "-e", f"HEAD:metadata/{version}.json")
        except subprocess.CalledProcessError:
            # Finish a local commit interrupted before pointer publication; no API replay.
            self.git("add", "--", f"snapshots/{version}", f"metadata/{version}.json")
            self.git(
                "-c",
                "user.name=ReflexForge",
                "-c",
                "user.email=reflexforge@localhost",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgSign=false",
                "commit",
                "-q",
                "-m",
                f"Accept {version}",
            )
        atomic_json(self.pointer, {"version": version})
        return version

    def rollback(self, version: str) -> None:
        path = self.snapshot(version)
        if AgentConfig.load(path).version != version:
            raise ValueError("snapshot hash mismatch")
        self.git("cat-file", "-e", f"HEAD:metadata/{version}.json")
        previous = self.active()
        atomic_json(self.pointer, {"version": version})
        from reflexforge.storage.traces import Trace

        Trace(self.directory / "audit.jsonl", "configuration").event(
            "rollback", {"from": previous[0] if previous else None, "to": version}
        )

    def history(self) -> list[dict[str, Any]]:
        history = []
        for path in sorted((self.repo / "metadata").glob("*.json")):
            try:
                commit = self.git("log", "-1", "--format=%H", "--", f"metadata/{path.name}")
            except subprocess.CalledProcessError:
                continue
            if commit:
                history.append({**json.loads(path.read_text()), "git_commit": commit})
        return history


def active_config_path(root: Path, suite: str = "debug") -> Path:
    from reflexforge.benchmark.suites import optimization_artifacts

    directory = optimization_artifacts(root, suite) / "real"
    if not (directory / "active.json").exists():
        return root / "config"
    active = VersionStore(directory).active()
    assert active is not None
    return active[1]
