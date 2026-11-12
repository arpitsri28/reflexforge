from decimal import Decimal
from datetime import datetime
def validate(row):
    for key in ('sale_id','currency','timestamp'):
        if not isinstance(row.get(key),str) or not row[key]: raise ValueError(key)
    if len(row['currency'])!=3: raise ValueError('currency')
    if datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).tzinfo is None: raise ValueError('timezone')
    if 'amount_cents' in row and int(row['amount_cents']) < 0: raise ValueError('amount')
    if 'amount_cents' not in row:
        amount=Decimal(row['amount'])
        if not amount.is_finite() or amount<0 or amount*100!=int(amount*100): raise ValueError('amount')
