import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from reader import read
assert read('{"data": {"full_name": "Ada Lovelace"}}') == {'name': 'Ada Lovelace'}
assert read('{"version": 2, "data": {"first": "Grace", "last": "Hopper"}}') == {'name': 'Grace Hopper'}
try: read('{"version": 3, "data": {"first": "x", "last": "y"}}')
except ValueError: pass
else: raise AssertionError('unknown version accepted')

print('REGRESSION_PASS', flush=True)
