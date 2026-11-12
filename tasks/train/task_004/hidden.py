import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from stock import Stock
from checkout import add_cart
s = Stock(5)
assert add_cart(s, 'a', 3) == 2
try: add_cart(s, 'b', 3)
except ValueError: pass
else: raise AssertionError('oversold')
assert s.reservations == {'a': 3}
s.cancel('a')
assert s.available() == 5
s.cancel('missing')
assert s.available() == 5

print('REGRESSION_PASS', flush=True)
