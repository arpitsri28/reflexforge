import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from aggregate import mean
assert mean([[(10, 1)], [(20, 3)]]) == 17.5
assert mean([[], [(9, 0)]]) is None
assert mean([[(10, 1), (20, 3)]]) == mean([[(10, 1)], [(20, 3)]])
assert mean([[(-2, 2)], [(2, 2)]]) == 0

print('REGRESSION_PASS', flush=True)
