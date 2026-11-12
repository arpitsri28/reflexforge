class ProfileCache:
    def __init__(self): self.values = {}
    def key(self, tenant, user): return user
    def get(self, tenant, user, loader):
        key = self.key(tenant, user)
        if key not in self.values: self.values[key] = loader(tenant, user)
        return self.values[key]
    def invalidate(self, tenant, user):
        self.values.pop(self.key(tenant, user), None)
