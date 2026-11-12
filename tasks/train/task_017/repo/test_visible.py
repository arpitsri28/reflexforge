from payments import Payments
from api import pay
calls = []
p = Payments(lambda amount: calls.append(amount) or len(calls))
assert pay(p, {'key': 'a', 'amount': 10}) == pay(p, {'key': 'a', 'amount': 10})
assert calls == [10]
