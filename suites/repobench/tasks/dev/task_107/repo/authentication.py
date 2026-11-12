class Authentication:
    def __init__(self,repository,tokens): self.repository,self.tokens=repository,dict(tokens)
    def authenticate(self,token):
        try: return self.repository.principals[self.tokens[token]]
        except KeyError: raise PermissionError('invalid token') from None
