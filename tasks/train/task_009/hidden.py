import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from settings import load
assert load({'DEBUG': ' FALSE '})['debug'] is False
assert load({'DEBUG': '1'})['debug'] is True
assert load({})['debug'] is False
for bad in ['yes', '', 7]:
    try: load({'DEBUG': bad})
    except ValueError: pass
    else: raise AssertionError('invalid value accepted')

print('REGRESSION_PASS', flush=True)
