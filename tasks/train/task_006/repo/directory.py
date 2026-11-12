class Directory:
    def __init__(self):
        self.entries = {}
        self.cached = None
    def put(self, name, value):
        self.entries[name] = value
    def delete(self, name):
        self.entries.pop(name, None)
    def listing(self):
        if self.cached is None: self.cached = sorted(self.entries)
        return self.cached
