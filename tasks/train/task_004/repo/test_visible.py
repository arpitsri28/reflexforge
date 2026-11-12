from stock import Stock
from checkout import add_cart
s = Stock(5)
assert add_cart(s, 'a', 3) == 2
