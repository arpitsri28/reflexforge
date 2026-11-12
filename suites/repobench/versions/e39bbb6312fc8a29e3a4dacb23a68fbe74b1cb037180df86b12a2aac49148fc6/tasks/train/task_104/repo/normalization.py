from datetime import datetime,timezone
from decimal import Decimal
def normalize(row):
    amount=int(row.get('amount_cents',row.get('amount',0)))
    day=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).astimezone(timezone.utc).date().isoformat()
    return {'id':row['sale_id'],'day':day,'currency':row['currency'].upper(),'cents':amount}
