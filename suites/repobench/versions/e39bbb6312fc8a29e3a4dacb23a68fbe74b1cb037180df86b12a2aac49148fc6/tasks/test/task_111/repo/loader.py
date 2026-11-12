from errors import DependencyCycle
class Loader:
    def __init__(self,registry,factories): self.registry,self.factories=registry,factories;self.instances={};self.active=[]
    def resolve(self,key):
        if key in self.instances: return self.instances[key]
        self.instances[key]=None
        definition=self.registry.get(key)
        dependencies={name:self.resolve(name) for name in definition.dependencies}
        value=self.factories.create(definition.kind,dependencies,definition.options)
        self.instances[key]=value
        return value
