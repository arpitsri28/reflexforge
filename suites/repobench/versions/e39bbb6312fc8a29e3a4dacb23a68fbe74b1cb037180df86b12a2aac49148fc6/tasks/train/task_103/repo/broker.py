class Broker:
    def __init__(self,messages): self.pending=list(messages);self.acks=[]
    def receive(self): return self.pending[0] if self.pending else None
    def ack(self,message):
        if message in self.pending: self.pending.remove(message)
        self.acks.append(message.key)
    def replay(self,message): self.pending.append(message)
