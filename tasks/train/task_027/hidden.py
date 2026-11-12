import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from batching import process
from converters import integer
values, errors = process(['1', 'bad', '2'], integer)
assert values == [1, None, 2] and list(errors) == [1]
assert 'bad' in errors[1]
assert process([], integer) == ([], {})
try: process(['1', 'offline', '2'], integer)
except RuntimeError as exc: assert str(exc) == 'unavailable'
else: raise AssertionError('infrastructure error swallowed')

print('REGRESSION_PASS', flush=True)
