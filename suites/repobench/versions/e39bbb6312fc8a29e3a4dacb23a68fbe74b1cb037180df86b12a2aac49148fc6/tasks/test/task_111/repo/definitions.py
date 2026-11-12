from dataclasses import dataclass,field
@dataclass(frozen=True)
class Definition:
    name:str
    kind:str
    dependencies:tuple=()
    options:dict=field(default_factory=dict)
