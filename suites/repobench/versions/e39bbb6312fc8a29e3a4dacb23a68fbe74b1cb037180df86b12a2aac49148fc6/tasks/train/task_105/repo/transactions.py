from contextlib import contextmanager
from copy import deepcopy
class Transactions:
    def __init__(self,store): self.store=store;self.snapshot=None;self.depth=0
    @contextmanager
    def begin(self):
        self.snapshot=deepcopy(self.store.data)
        try: yield self.store
        except BaseException:
            self.store.restore(self.snapshot)
            raise
        finally: self.snapshot=None
