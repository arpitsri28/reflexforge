class Registry:
    def __init__(self,definitions):
        self.definitions={}
        for definition in definitions:
            if definition.name in self.definitions: raise ValueError('duplicate provider')
            self.definitions[definition.name]=definition
    def get(self,name): return self.definitions[name]
