from urllib.parse import parse_qs
from links import search_link
assert parse_qs(search_link({'q': 'a&b'}) .split('?', 1)[1]) == {'q': ['a&b']}
