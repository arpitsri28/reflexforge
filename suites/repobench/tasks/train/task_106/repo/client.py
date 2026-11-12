from protocol import HTTPError
class Client:
    def __init__(self,transport,attempts=2): self.transport,self.attempts=transport,attempts
    def page(self,cursor):
        for attempt in range(self.attempts):
            response=self.transport.get(cursor)
            if response.status==200: return response.body
            if response.status!=503 or attempt+1==self.attempts: raise HTTPError(str(response.status))
        raise HTTPError('no request attempts')
