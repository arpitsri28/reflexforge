import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from config import resolve
base = {'db': {'host': 'local', 'port': 1}, 'tags': ['a']}
override = {'db': {'port': 2}, 'extra': ['x']}
result = resolve(base, override)
assert result['db'] == {'host': 'local', 'port': 2}
result['tags'].append('b')
result['extra'].append('y')
assert base['tags'] == ['a'] and override['extra'] == ['x']
assert resolve({'db': {'port': 1}}, {'db': None})['db'] is None

print('REGRESSION_PASS', flush=True)
