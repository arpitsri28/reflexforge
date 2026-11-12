from tokenization import prepare
from query import search
from facets import counts
class Search:
    def __init__(self,store,index): self.store,self.index=store,index
    def put(self,document):
        self.store.put(document)
        terms=prepare(document)
        self.index.replace(document.key,terms)
    def delete(self,key): self.index.remove(key);self.store.remove(key)
    def find(self,text): return search(self.store,self.index,text)
    def facets(self): return counts(self.index)
