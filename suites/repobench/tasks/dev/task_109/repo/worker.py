class Worker:
    def __init__(self,events): self.events=events;self.running=False
    def start(self): self.running=True;self.events.append(('worker','start'))
    def drain(self):
        if self.running: self.events.append(('worker','drain'));self.running=False
