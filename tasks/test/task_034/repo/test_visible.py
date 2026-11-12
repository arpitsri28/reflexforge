from reader import read
assert read('{"data": {"full_name": "Ada Lovelace"}}') == {'name': 'Ada Lovelace'}
