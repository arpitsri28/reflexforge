"""Materialize trusted RepoBench authoring strings; never execute task code on host."""

import ast
import json
import shutil
from pathlib import Path

from repobench_catalog import CASES

from reflexforge.benchmark.manifest import Entry, digest, task_content
from reflexforge.schema import Budget, Task

ROOT = Path(__file__).resolve().parents[1] / "suites" / "repobench"
PRIVATE = ROOT / "benchmark"
HIDDEN_HEADER = "import sys,unittest,json\nsys.path.insert(0,'/workspace')\n"
HIDDEN_FOOTER = """
suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
"""
entries, specifications = [], {}
for data in CASES:
    number = data["number"]
    split = "train" if number <= 106 else "dev" if number <= 110 else "test"
    task_id = f"task_{number:03}"
    directory = ROOT / "tasks" / split / task_id
    for name, source in data["modules"].items():
        ast.parse(source)
        path = directory / "repo" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    tests = directory / "repo" / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_application.py").write_text(data["visible"])
    (directory / "repo" / "README.md").write_text(
        "# "
        + data["domain"].replace("-", " ").title()
        + "\n\n"
        + data["contract"]
        + "\n\nRun the public suite: `python -m unittest discover -s tests -v`.\n"
        "This repository uses the Python standard library and runs offline.\n"
    )
    hidden = HIDDEN_HEADER + data["hidden"] + HIDDEN_FOOTER
    ast.parse(hidden)
    (directory / "hidden.py").write_text(hidden)
    task = Task(
        id=task_id,
        split=split,
        repository="repo",
        issue=data["issue"],
        setup="",
        reproduction="python -m unittest discover -s tests -v",
        editable=list(data["modules"]),
        budget=Budget(
            max_steps=30,
            max_tokens=40000,
            response_tokens=4096,
            wall_seconds=300,
            command_seconds=30,
            retry_limit=0,
        ),
    )
    (directory / "task.json").write_text(task.model_dump_json(indent=2) + "\n")
    for kind, overlay in [("references", data["reference"]), ("mutants", data["mutant"])]:
        (PRIVATE / kind).mkdir(parents=True, exist_ok=True)
        (PRIVATE / kind / f"{task_id}.json").write_text(json.dumps(overlay, indent=2) + "\n")

    def count_tests(source):
        return sum(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
            for n in ast.walk(ast.parse(source))
        )

    graph = {}
    names = {Path(name).stem: name for name in data["modules"]}
    for name, source in data["modules"].items():
        imports = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports += [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.split(".")[0])
        graph[name] = sorted({names[item] for item in imports if item in names})

    def depth(name, seen=()):
        if name in seen:
            return 0
        return max((1 + depth(child, seen + (name,)) for child in graph[name]), default=0)

    specifications[task_id] = {
        "domain": data["domain"],
        "root_cause": data["root_cause"],
        "dependency_path": data["dependency_path"],
        "module_roles": data["roles"],
        "meaningful_modules": len(data["modules"]),
        "dependency_depth": max(depth(name) for name in graph),
        "dependency_depth_metric": "longest local import path; injected runtime dependencies are additional",
        "local_import_graph": graph,
        "dependency_path_kind": "symptom-to-cause investigation/dataflow components",
        "plausible_failure_locations": len(data["dependency_path"]),
        "debugging_operations": [
            "reproduce public failure",
            "trace contracts across dependency boundaries",
            "inspect state before and after exceptions",
            "repair coordinated invariants",
            "run preservation and regression suites",
        ],
        "state_invariants": data["invariants"],
        "empirical_difficulty": None,
        "public_test_count": count_tests(data["visible"]),
        "hidden_test_count": count_tests(data["hidden"]),
        "mutant_hash": digest(data["mutant"]),
    }
    entries.append(
        Entry(
            id=task_id,
            split=split,
            family=data["domain"],
            category=data["domain"],
            difficulty="hard",
            affected_modules=len(data["reference"]),
            prior_agent_exposure=False,
            coverage=data["invariants"],
            task_path=f"tasks/{split}/{task_id}/task.json",
            source_hash=digest(task_content(task, directory)),
            reference_hash=digest(data["reference"]),
        ).model_dump()
    )
(PRIVATE / "specification.json").write_text(json.dumps(specifications, indent=2) + "\n")
content = {
    "suite": "repobench",
    "specification_hash": digest(specifications),
    "provenance": "project-authored synthetic debugging fixtures",
    "entries": entries,
}
(PRIVATE / "manifest.json").write_text(
    json.dumps({"format_version": 2, "version": digest(content), **content}, indent=2) + "\n"
)
print("RepoBench repositories:", len(entries), "version:", digest(content))

snapshot = ROOT / "versions" / digest(content)
if not snapshot.exists():
    snapshot.mkdir(parents=True)
    for part in ("tasks", "benchmark"):
        shutil.copytree(
            ROOT / part,
            snapshot / part,
            ignore=shutil.ignore_patterns("validation.json") if part == "benchmark" else None,
        )
