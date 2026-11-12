from dataclasses import replace
class Repository:
    def __init__(self,principals,documents):
        self.principals={p.key:p for p in principals};self.documents={d.key:d for d in documents}
    def roles(self,key,admin):
        p=self.principals[key];self.principals[key]=replace(p,admin=admin,revision=p.revision+1)
    def update_document(self,key,**changes):
        d=self.documents[key];self.documents[key]=replace(d,revision=d.revision+1,**changes)
