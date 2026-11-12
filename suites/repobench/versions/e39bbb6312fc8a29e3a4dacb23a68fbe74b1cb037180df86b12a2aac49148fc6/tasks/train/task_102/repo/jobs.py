from dataclasses import dataclass
@dataclass
class Job:
    key: str
    payload: int
    state: str = 'queued'
    attempts: int = 0
