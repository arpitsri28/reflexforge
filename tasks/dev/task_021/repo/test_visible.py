from events import ordered, utc_time
rows = [{'id': 1, 'time': '2024-01-01T10:00:00+02:00'}, {'id': 2, 'time': '2024-01-01T09:00:00Z'}]
assert [r['id'] for r in ordered(rows)] == [1, 2]
assert utc_time(rows[0]) == '2024-01-01T08:00:00+00:00'
