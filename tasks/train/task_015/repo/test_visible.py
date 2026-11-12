from client import values
pages = {None: {'items': [], 'next_cursor': 'a'}, 'a': {'items': [{'value': 7}], 'next_cursor': None}}
assert values(pages.__getitem__) == [7]
