import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from payments import Payments
calls = []
p = Payments(lambda amount: calls.append(amount) or len(calls))
assert p.submit('a', 10) == p.submit('a', 10)
assert calls == [10]
try: p.submit('a', 20)
except ValueError: pass
else: raise AssertionError('conflict accepted')
assert calls == [10]
assert p.submit('b', 20) == 2
attempts = []
def fail(amount):
    attempts.append(amount)
    raise RuntimeError('declined')
f = Payments(fail)
for _ in range(2):
    try: f.submit('a', 1)
    except RuntimeError: pass
assert attempts == [1, 1] and f.receipts == {}

print('REGRESSION_PASS', flush=True)
