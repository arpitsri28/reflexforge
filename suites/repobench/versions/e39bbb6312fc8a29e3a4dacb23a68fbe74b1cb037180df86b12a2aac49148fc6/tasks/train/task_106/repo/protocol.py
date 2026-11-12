from dataclasses import dataclass
@dataclass
class Response:
    status:int
    body:dict
class HTTPError(RuntimeError): pass
class BatchError(RuntimeError): pass
