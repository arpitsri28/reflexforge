from dataclasses import dataclass
@dataclass(frozen=True)
class Principal:
    key:str
    tenant:str
    admin:bool=False
    revision:int=0
@dataclass(frozen=True)
class Document:
    key:str
    tenant:str
    owner:str
    body:str
    public:bool=False
    revision:int=0
