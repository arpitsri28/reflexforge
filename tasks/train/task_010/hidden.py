import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
import json
from money import Money
from wire import encode, decode
for value in ['9007199254740993.01', '0.00000000000000001', '-12.30']:
    m = Money(value, 'CAD')
    data = encode(m)
    assert isinstance(json.loads(data)['amount'], str)
    restored = decode(data)
    assert restored.amount == m.amount and restored.currency == 'CAD'

print('REGRESSION_PASS', flush=True)
