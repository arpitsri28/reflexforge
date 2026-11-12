from money import Money
from wire import encode, decode
m = Money('9007199254740993.01', 'CAD')
assert decode(encode(m)).amount == m.amount
