import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from codes import Codes
from login import login
c = Codes()
c.issue('a', 'u', 10)
assert login(c, 'a', 9) == {'session_user': 'u'}
try: login(c, 'a', 9)
except KeyError: pass
else: raise AssertionError('replayed login')
c.issue('b', 'v', 10)
try: login(c, 'b', 10)
except ValueError: pass
else: raise AssertionError('expiry boundary accepted')
assert c.values['b'] == ('v', 10)

print('REGRESSION_PASS', flush=True)
