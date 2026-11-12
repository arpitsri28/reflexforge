import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from service import append
data = {'items': [1], 'nested': {'flag': True}}
assert append(data, 2) is data
assert data['items'] == [1, 2]
try: append(data, 3, True)
except ValueError: pass
else: raise AssertionError('error swallowed')
assert data == {'items': [1, 2], 'nested': {'flag': True}}

print('REGRESSION_PASS', flush=True)
