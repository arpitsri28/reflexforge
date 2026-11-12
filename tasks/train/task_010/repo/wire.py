import json
from money import Money
def encode(money):
    return json.dumps({'amount': float(money.amount), 'currency': money.currency})
def decode(data):
    fields = json.loads(data)
    return Money(fields['amount'], fields['currency'])
