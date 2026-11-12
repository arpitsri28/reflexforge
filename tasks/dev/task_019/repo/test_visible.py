from dashboard import ids
assert ids([[{'id': 'a', 'priority': 2}], [{'id': 'z', 'priority': 2}]]) == ['a', 'z']
