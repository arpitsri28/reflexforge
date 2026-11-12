import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from app import create
r = create()
assert r.resolve('/users/me') == 'self'
assert r.resolve('/users/42') == 'user'
for path in ['/users/42/edit', '/users/', '/other/42']:
    try: r.resolve(path)
    except KeyError: pass
    else: raise AssertionError('nonmatching route accepted')

print('REGRESSION_PASS', flush=True)
