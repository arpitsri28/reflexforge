from copy import deepcopy
class Store:
    def __init__(self,accounts): self.data={'accounts':dict(accounts),'audit':[]}
    def restore(self,snapshot):
        self.data=deepcopy(snapshot)
    def account_view(self): return self.data['accounts']
    def audit_view(self): return self.data['audit']
