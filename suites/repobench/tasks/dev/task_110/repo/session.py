from payloads import decode
class Session:
    def __init__(self,router): self.router=router;self.last=0
    def accept(self,frame):
        event=decode(frame)
        if event['seq']<=self.last: return None
        result=self.router.apply(event);self.last=event['seq']
        return result
