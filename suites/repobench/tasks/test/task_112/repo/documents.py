from dataclasses import dataclass
@dataclass(frozen=True)
class Document:
    key:str
    title:str
    body:str=''
