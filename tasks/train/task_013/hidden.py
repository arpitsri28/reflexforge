import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from summary import summarize
assert summarize(iter([2, None, 3])) == {'count': 2, 'total': 5}
assert summarize(iter([])) == {'count': 0, 'total': 0}
assert summarize([0, -2, None]) == {'count': 2, 'total': -2}

print('REGRESSION_PASS', flush=True)
