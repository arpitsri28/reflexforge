import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from export import export
assert export(iter([1, 2, 3]), 2) == [[1, 2], [3]]
assert export([], 2) == []
assert export([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
try: export([1], 0)
except ValueError: pass
else: raise AssertionError('invalid size')

print('REGRESSION_PASS', flush=True)
