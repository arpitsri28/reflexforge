import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from request import credentials
assert credentials({'Authorization': 'bearer AbC'}) == 'AbC'
assert credentials({'Authorization': ' Bearer\txyz '}) == 'xyz'
for value in ['Basic abc', 'Bearer', 'Bearer a b', '']:
    try: credentials({'Authorization': value})
    except ValueError: pass
    else: raise AssertionError('invalid header accepted')

print('REGRESSION_PASS', flush=True)
