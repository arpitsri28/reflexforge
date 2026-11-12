import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from intervals import coalesce
from schedule import occupied
assert coalesce([(1, 10), (2, 3), (10, 12)]) == [(1, 12)]
assert occupied([(5, 7), (1, 2)]) == 3
assert coalesce([(2, 2)]) == []
try: coalesce([(3, 1)])
except ValueError: pass
else: raise AssertionError('reversed interval')

print('REGRESSION_PASS', flush=True)
