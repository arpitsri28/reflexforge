class Audit:
    def __init__(self): self.events = []
    def completed(self, request, receipt):
        self.events.append((request.account, request.key, receipt['id']))
    def for_account(self, account): return [e for e in self.events if e[0] == account]
