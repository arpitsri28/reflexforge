class Codes:
    def __init__(self): self.values = {}
    def issue(self, code, user, expires): self.values[code] = (user, expires)
    def redeem(self, code, now):
        user, expires = self.values[code]
        if now > expires: raise ValueError('expired')
        return user
