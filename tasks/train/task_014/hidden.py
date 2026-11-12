import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from work import execute
class Connection:
    def __init__(self): self.closed = 0
    def close(self): self.closed += 1
c = Connection()
assert execute(lambda: c, lambda c: 42) == 42
assert c.closed == 1
c = Connection()
def fail(c): raise ValueError('body')
try: execute(lambda: c, fail)
except ValueError as e: assert str(e) == 'body'
else: raise AssertionError('exception suppressed')
assert c.closed == 1

print('REGRESSION_PASS', flush=True)
