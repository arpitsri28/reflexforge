"""Initialize environment settings relative to the source repository, not the shell."""

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_environment() -> None:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
