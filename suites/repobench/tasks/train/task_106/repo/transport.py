from protocol import Response
class Transport:
    def __init__(self,pages): self.pages=pages;self.failures={};self.requests=[]
    def get(self,cursor):
        self.requests.append(cursor)
        if self.failures.get(cursor,0):
            self.failures[cursor]-=1;return Response(503,{})
        return Response(200,self.pages[cursor])
