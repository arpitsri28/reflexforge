from copy import deepcopy
class Factories:
    def __init__(self): self.builders={};self.calls={}
    def register(self,kind,builder): self.builders[kind]=builder
    def create(self,kind,dependencies,options):
        self.calls[kind]=self.calls.get(kind,0)+1
        return self.builders[kind](dependencies,deepcopy(options))
