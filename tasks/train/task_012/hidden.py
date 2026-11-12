import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from shop.orders import total
assert total([]) == 0
assert total([('pen', 2), ('book', 1)]) == 13
assert total([('book', 0)]) == 0
try: total([('missing', 1)])
except KeyError: pass
else: raise AssertionError('unknown product must fail')

print('REGRESSION_PASS', flush=True)
