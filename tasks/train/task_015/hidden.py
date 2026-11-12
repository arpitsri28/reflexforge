import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from client import values
pages = {None: {'items': [], 'next_cursor': 'a'}, 'a': {'items': [{'value': 7}], 'next_cursor': None}}
assert values(pages.__getitem__) == [7]
assert values(lambda c: {'items': [{'value': 2}], 'next_cursor': None}) == [2]
try: values(lambda c: {'items': [], 'next_cursor': 'same'})
except ValueError: pass
else: raise AssertionError('cycle not rejected')

print('REGRESSION_PASS', flush=True)
