class Documents:
    def __init__(self,repository,decisions,policy): self.repository,self.decisions,self.policy=repository,decisions,policy
    def read(self,principal,key):
        document=self.repository.documents[key]
        if not self.decisions.allowed(principal,document,'read',self.policy): raise PermissionError('denied')
        return {'id':document.key,'body':document.body}
