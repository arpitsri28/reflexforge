class Decisions:
    def __init__(self): self.values={}
    def key(self,principal,document,action):
        return (document.key, action)
    def allowed(self,principal,document,action,policy):
        key=self.key(principal,document,action)
        if key not in self.values: self.values[key]=policy.allows(principal,document,action)
        return self.values[key]
