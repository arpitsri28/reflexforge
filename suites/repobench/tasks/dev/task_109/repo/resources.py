class Resource:
    def __init__(self,name,events,fail=None): self.name,self.events,self.fail=name,events,fail;self.opened=False;self.closed=False
    def open(self):
        self.events.append(('open',self.name));self.opened=True
        if self.fail=='open': raise ValueError('open '+self.name)
    def validate(self):
        self.events.append(('validate',self.name))
        if self.fail=='validate': raise ValueError('validate '+self.name)
    def close(self):
        if self.closed: return
        self.events.append(('close',self.name));self.closed=True;self.opened=False
        if self.fail=='close': raise RuntimeError('close '+self.name)
