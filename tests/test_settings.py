import os
import shutil
import subprocess
import sys

from conftest import ROOT

from reflexforge import settings


def test_dotenv_loads_from_repository_regardless_of_cwd(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".env").write_text("OPENAI_API_KEY=fake-unit-test-key\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".env").write_text("OPENAI_API_KEY=wrong-file\n")
    monkeypatch.chdir(outside)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "PROJECT_ROOT", repository)
    settings.load_environment()
    assert os.getenv("OPENAI_API_KEY") == "fake-unit-test-key"


def test_dotenv_preserves_explicit_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENAI_MODEL=file-model\n")
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("OPENAI_MODEL", "explicit-model")
    settings.load_environment()
    assert os.getenv("OPENAI_MODEL") == "explicit-model"


def test_package_initializes_dotenv_before_submodules(tmp_path):
    # Run the real initialization code against a fake repository and dummy key.
    package = tmp_path / "repo" / "src" / "reflexforge"
    package.mkdir(parents=True)
    for name in ("__init__.py", "settings.py"):
        shutil.copyfile(ROOT / "src" / "reflexforge" / name, package / name)
    (package.parents[1] / ".env").write_text("OPENAI_API_KEY=fake-startup-key\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    environment = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    environment["PYTHONPATH"] = str(package.parent)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import reflexforge, os; assert os.getenv('OPENAI_API_KEY') == 'fake-startup-key'",
        ],
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
