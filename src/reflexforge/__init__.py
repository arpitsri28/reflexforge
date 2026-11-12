from reflexforge.settings import load_environment

# Initialize before CLI, worker, or sandbox modules read environment settings.
load_environment()

__version__ = "0.1.0"
