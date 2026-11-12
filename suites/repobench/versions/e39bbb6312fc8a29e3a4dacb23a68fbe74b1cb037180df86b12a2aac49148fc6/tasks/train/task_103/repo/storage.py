from contextlib import contextmanager
from copy import deepcopy
class Store:
    def __init__(self): self.balances={};self.seen=set();self.audit=[]
    @contextmanager
    def atomic(self):
        before=deepcopy((self.balances,self.seen,self.audit))
        try: yield self
        except BaseException:
            self.balances,self.seen,self.audit=before
            raise
