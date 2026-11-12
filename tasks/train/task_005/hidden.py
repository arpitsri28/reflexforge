import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from cache import ProfileCache
from profiles import load_profile
c = ProfileCache()
a = c.get('red', '42', load_profile)
b = c.get('blue', '42', load_profile)
assert a['tenant'] == 'red' and b['tenant'] == 'blue'
assert c.get('red', '42', load_profile) is a
c.invalidate('red', '42')
assert c.get('red', '42', load_profile) is not a
assert c.get('blue', '42', load_profile) is b

print('REGRESSION_PASS', flush=True)
