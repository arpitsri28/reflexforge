import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from export import transfer
assert transfer([['a,b', 'c'], ['say "yes"', '']]) == [['a,b', 'c'], ['say "yes"', '']]
assert transfer([['line1\nline2', 'x']]) == [['line1\nline2', 'x']]
assert transfer([]) == []

print('REGRESSION_PASS', flush=True)
