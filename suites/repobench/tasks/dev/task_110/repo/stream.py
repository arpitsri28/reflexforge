from framing import Decoder
from router import Router
from session import Session
class Stream:
    def __init__(self): self.decoder=Decoder();self.router=Router();self.session=Session(self.router)
    def receive(self,data):
        result=[]
        for frame in self.decoder.feed(data):
            value=self.session.accept(frame)
            if value is not None: result.append(value)
        return result
