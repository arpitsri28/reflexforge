import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from dashboard import ids
from ordering import merge
a = [{'id': 'a', 'priority': 2}, {'id': 'b', 'priority': 0}]
b = [{'id': 'z', 'priority': 2}, {'id': 'q', 'priority': 3}]
assert ids([a, b]) == ['q', 'a', 'z', 'b']
rows = merge([a])
rows[0]['id'] = 'changed'
assert a[0]['id'] == 'a'
assert ids([]) == []

print('REGRESSION_PASS', flush=True)
