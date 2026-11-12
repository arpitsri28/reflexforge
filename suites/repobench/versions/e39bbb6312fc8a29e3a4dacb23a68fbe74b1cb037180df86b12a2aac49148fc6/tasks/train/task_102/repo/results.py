class Results:
    def __init__(self): self.values={}
    def put(self,key,value): self.values[key]=value
    def get(self,key): return self.values[key]
