import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from build import plan
assert plan({'a': ['b', 'c'], 'b': ['d'], 'c': ['d'], 'd': []}, 'a') == ('d', 'b', 'c', 'a')
assert plan({'a': []}, 'a') == ('a',)
try: plan({'a': ['a']}, 'a')
except ValueError: pass
else: raise AssertionError('self cycle accepted')
try: plan({'a': ['missing']}, 'a')
except KeyError: pass
else: raise AssertionError('missing node swallowed')

print('REGRESSION_PASS', flush=True)
