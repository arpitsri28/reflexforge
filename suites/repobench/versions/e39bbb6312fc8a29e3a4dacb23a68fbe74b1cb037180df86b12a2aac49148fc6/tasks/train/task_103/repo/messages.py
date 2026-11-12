from dataclasses import dataclass
@dataclass(frozen=True)
class Message:
    key: str
    account: str
    delta: int
