import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from reflexforge.schema import StrictModel, Task
from reflexforge.tasks import fixture_files


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Entry(StrictModel):
    id: str
    split: Literal["train", "dev", "test"]
    family: str
    category: str
    difficulty: Literal["easy", "medium", "hard"]
    affected_modules: int = Field(ge=1)
    prior_agent_exposure: bool = False
    coverage: list[str] = Field(min_length=3)
    task_path: str
    source_hash: str
    reference_hash: str


class Manifest(StrictModel):
    format_version: int = 1
    provenance: Literal["project-authored synthetic debugging fixtures"]
    version: str
    entries: list[Entry]


class RepoManifest(Manifest):
    format_version: Literal[2] = 2
    suite: Literal["repobench"] = "repobench"
    specification_hash: str


def task_content(task: Task, directory: Path) -> dict[str, Any]:
    hidden = directory / task.hidden_test
    if hidden.is_symlink() or not hidden.resolve().is_relative_to(directory.resolve()):
        raise ValueError("hidden test escapes task directory")
    original = fixture_files(task, directory)
    if hidden.resolve().is_relative_to((directory / task.repository).resolve()):
        raise ValueError("hidden tests must be outside worker repository")
    if any("reference" in Path(name).parts for name in original):
        raise ValueError("reference content in worker repository")
    return {
        "task": json.loads((directory / "task.json").read_text()),
        "repository": original,
        "hidden": hidden.read_text(),
    }


def load_manifest(root: Path, expected_version: str | None = None) -> Manifest:
    raw = json.loads((root / "benchmark" / "manifest.json").read_text())
    manifest = (RepoManifest if raw.get("format_version") == 2 else Manifest).model_validate(raw)
    content = {
        "provenance": manifest.provenance,
        "entries": [e.model_dump() for e in manifest.entries],
    }
    if isinstance(manifest, RepoManifest):
        content.update(suite=manifest.suite, specification_hash=manifest.specification_hash)
    calculated = digest(content)
    if (
        manifest.version != calculated
        or expected_version is not None
        and expected_version != calculated
    ):
        raise ValueError("benchmark version/hash mismatch")
    ids, families = set(), {}
    for entry in manifest.entries:
        if entry.id in ids:
            raise ValueError("duplicate task id")
        ids.add(entry.id)
        if entry.family in families and families[entry.family] != entry.split:
            raise ValueError("related family crosses splits")
        families[entry.family] = entry.split
        if entry.task_path != f"tasks/{entry.split}/{entry.id}/task.json":
            raise ValueError("unsafe manifest path")
    return manifest


def resolve_entry(
    root: Path, entry: Entry, *, references: bool = False
) -> tuple[Task, Path, dict[str, str] | None]:
    path = root / entry.task_path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("manifest task path escapes benchmark")
    task = Task.model_validate(json.loads(path.read_text()))
    if task.id != entry.id or task.split != entry.split:
        raise ValueError("manifest task identity mismatch")
    if digest(task_content(task, path.parent)) != entry.source_hash:
        raise ValueError(f"fixture hash mismatch: {entry.id}")
    patch = None
    if references:
        reference = root / "benchmark" / "references" / f"{entry.id}.json"
        if reference.is_symlink() or not reference.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe reference file")
        patch = json.loads(reference.read_text())
        if (
            not isinstance(patch, dict)
            or not patch
            or not all(isinstance(v, str) for v in patch.values())
        ):
            raise ValueError("invalid reference overlay")
        if not set(patch) <= set(task.editable) or digest(patch) != entry.reference_hash:
            raise ValueError("reference hash or source allowlist mismatch")
    return task, path.parent, patch


def load_specification(root: Path, manifest: RepoManifest) -> dict[str, Any]:
    path = root / "benchmark" / "specification.json"
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("private specification path escapes suite")
    specification = json.loads(path.read_text())
    if digest(specification) != manifest.specification_hash:
        raise ValueError("private specification hash mismatch")
    return specification


def normalized_source(files: dict[str, str]) -> str:
    # Structural normalization catches renamed copies; source is parsed, never imported.
    class Normalize(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

        def visit_arg(self, node: ast.arg) -> ast.AST:
            node.arg = "_"
            return node

        def visit_Constant(self, node: ast.Constant) -> ast.AST:
            return ast.copy_location(ast.Constant(value=type(node.value).__name__), node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
            node.name = "_"
            return self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
            node.name = "_"
            return self.generic_visit(node)

    return "\n".join(
        ast.dump(Normalize().visit(ast.parse(content)), include_attributes=False)
        for name, content in sorted(files.items())
        if content.strip() and not name.startswith("test_")
    )


def inspect_bank(root: Path, manifest: Manifest) -> dict[str, Any]:
    import re
    from difflib import SequenceMatcher

    sources, duplicates = [], []
    for entry in manifest.entries:
        task, directory, patch = resolve_entry(root, entry, references=True)
        original = fixture_files(task, directory)
        if patch == {name: original[name] for name in patch}:
            raise ValueError("reference overlay does not change buggy source")
        for name, content in (original | patch).items():
            if name.endswith(".py"):
                ast.parse(content, filename=name)
        ast.parse((directory / task.hidden_test).read_text())
        source = normalized_source({n: c for n, c in original.items() if n in task.editable})
        for previous, other in sources:
            matcher = SequenceMatcher(
                None, re.findall(r"\w+", source), re.findall(r"\w+", other), autojunk=False
            )
            # quick_ratio is an upper bound: skip expensive alignment only when
            # it cannot possibly meet the existing duplicate threshold.
            if matcher.quick_ratio() < 0.92:
                continue
            similarity = matcher.ratio()
            if similarity >= 0.92:
                duplicates.append(
                    {
                        "tasks": [previous.id, entry.id],
                        "similarity": similarity,
                        "cross_split": previous.split != entry.split,
                    }
                )
        sources.append((entry, source))
    if any(pair["cross_split"] for pair in duplicates):
        raise ValueError(f"cross-split near-duplicate fixtures: {duplicates}")
    structural = {}
    if isinstance(manifest, RepoManifest):
        specification = load_specification(root, manifest)
        for entry in manifest.entries:
            spec = specification[entry.id]
            task, directory, _ = resolve_entry(root, entry)
            modules = fixture_files(task, directory)
            if set(spec["module_roles"]) != set(task.editable) or len(spec["module_roles"]) < 5:
                raise ValueError("RepoBench requires meaningful, documented source modules")
            if len(set(spec["dependency_path"])) < 3 or not set(spec["dependency_path"]) <= set(
                task.editable
            ):
                raise ValueError("invalid private dependency path")
            if any(
                not modules[name].strip() or not ast.parse(modules[name]).body
                for name in task.editable
            ):
                raise ValueError("empty source module does not count as repository complexity")
            structural[entry.id] = {
                key: spec[key]
                for key in (
                    "meaningful_modules",
                    "dependency_depth",
                    "plausible_failure_locations",
                    "debugging_operations",
                    "state_invariants",
                    "empirical_difficulty",
                )
            }
    return {
        "suite": getattr(manifest, "suite", "debug"),
        "structural": structural,
        "version": manifest.version,
        "provenance": manifest.provenance,
        "split_counts": dict(Counter(e.split for e in manifest.entries)),
        "difficulty_counts": dict(Counter(e.difficulty for e in manifest.entries)),
        "category_counts": dict(Counter(e.category for e in manifest.entries)),
        "near_duplicates": duplicates,
        "tasks": [e.model_dump() for e in manifest.entries],
    }
