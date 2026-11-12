from cleanup import release
class Pool:
    def __init__(self): self.resources=[];self.state='stopped';self.errors=[]
    def start(self,factories):
        if self.state!='stopped': raise RuntimeError('already started')
        self.state='starting'
        try:
            for factory in factories:
                resource=factory()
                resource.open()
                resource.validate()
                self.resources.append(resource)
            self.state='ready'
        except Exception:
            self.errors=release(self.resources)
            self.resources=[]
            raise
    def stop(self):
        if self.state=='stopped': return
        self.errors=release(self.resources);self.resources=[];self.state='stopped'
