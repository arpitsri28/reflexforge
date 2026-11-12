import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from job import run
closed = []
class R:
    def __init__(self, name): self.name = name
    def close(self): closed.append(self.name)
assert run([lambda: R('a'), lambda: R('b')], len) == 2
assert closed == ['b', 'a']
closed.clear()
def fail(): raise ValueError('acquire')
try: run([lambda: R('a'), fail], len)
except ValueError: pass
else: raise AssertionError('acquisition failure hidden')
assert closed == ['a']
assert run([], len) == 0

print('REGRESSION_PASS', flush=True)
