import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from events import ordered, utc_time
from dates import parse
rows = [{'id': 1, 'time': '2024-01-01T10:00:00+02:00'}, {'id': 2, 'time': '2024-01-01T09:00:00Z'}]
assert [r['id'] for r in ordered(rows)] == [1, 2]
assert utc_time(rows[0]) == '2024-01-01T08:00:00+00:00'
same = [{'id': 'a', 'time': '2024-01-01T08:00:00Z'}, {'id': 'b', 'time': '2024-01-01T10:00:00+02:00'}]
assert [r['id'] for r in ordered(same)] == ['a', 'b']
try: parse('2024-01-01T10:00:00')
except ValueError: pass
else: raise AssertionError('naive timestamp accepted')

print('REGRESSION_PASS', flush=True)
