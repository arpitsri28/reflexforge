class Policy:
    def __init__(self): self.evaluations=0
    def allows(self,principal,document,action):
        self.evaluations+=1
        if action!='read' or principal.tenant!=document.tenant: return False
        return principal.admin or principal.key==document.owner or document.public
