class Index:
    def __init__(self): self.postings={};self.document_terms={}
    def replace(self,key,terms):
        for term in terms: self.postings.setdefault(term,set()).add(key)
        self.document_terms[key]=set(terms)
    def remove(self,key):
        for term in self.document_terms.pop(key,set()):
            self.postings[term].discard(key)
            if not self.postings[term]: del self.postings[term]
