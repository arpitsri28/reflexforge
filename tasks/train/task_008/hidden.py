import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from retrying import retry
calls = []
def transient():
    calls.append(1)
    if len(calls) < 3: raise TimeoutError('later')
    return 'ok'
assert retry(transient, 3) == 'ok'
assert len(calls) == 3
calls.clear()
def invalid():
    calls.append(1)
    raise ValueError('bad')
try: retry(invalid, 3)
except ValueError: pass
assert len(calls) == 1
calls.clear()
try: retry(invalid, 0)
except ValueError: pass
assert calls == []

print('REGRESSION_PASS', flush=True)
