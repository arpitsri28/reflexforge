"""Suite routing preserves legacy paths and isolates RepoBench state."""

from pathlib import Path


def dataset_root(root: Path, suite: str = "debug") -> Path:
    if suite not in {"debug", "repobench"}:
        raise ValueError("suite must be debug or repobench")
    return root if suite == "debug" else root / "suites" / "repobench"


def benchmark_artifacts(root: Path, suite: str = "debug") -> Path:
    dataset_root(root, suite)  # Validate before constructing any path.
    path = root / "artifacts" / "benchmark"
    return path if suite == "debug" else path / suite


def optimization_artifacts(root: Path, suite: str = "debug") -> Path:
    dataset_root(root, suite)
    path = root / "artifacts" / "optimization"
    return path if suite == "debug" else path / suite
