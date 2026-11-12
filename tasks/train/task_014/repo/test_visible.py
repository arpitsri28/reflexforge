from work import execute
class Connection:
    closed = 0
    def close(self): self.closed += 1
c = Connection()
def fail(c): raise ValueError('body')
try: execute(lambda: c, fail)
except ValueError: pass
assert c.closed == 1
