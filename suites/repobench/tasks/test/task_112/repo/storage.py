class Store:
    def __init__(self): self.documents={}
    def put(self,document): self.documents[document.key]=document
    def remove(self,key): self.documents.pop(key,None)
    def get(self,key): return self.documents[key]
