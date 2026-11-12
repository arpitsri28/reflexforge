class Router:
    def __init__(self): self.total=0;self.labels=[];self.pings=0
    def apply(self,event):
        if event['kind']=='ping': self.pings+=1
        else: self.total+=event['amount'];self.labels.append(event['label'])
        return self.total
