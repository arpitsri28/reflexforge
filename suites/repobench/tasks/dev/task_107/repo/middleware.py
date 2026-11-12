class Middleware:
    def __init__(self,authentication,service): self.authentication,self.service=authentication,service
    def request(self,token,key):
        principal=self.authentication.authenticate(token)
        return self.service.read(principal,key)
