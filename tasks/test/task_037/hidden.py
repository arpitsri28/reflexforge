import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from urllib.parse import parse_qs
from links import search_link
def decode(params): return parse_qs(search_link(params).split('?', 1)[1])
assert decode({'q': 'a&b + café'}) == {'q': ['a&b + café']}
assert decode({'tag': ['x', 'y']}) == {'tag': ['x', 'y']}
assert decode({'tag': []}) == {}

print('REGRESSION_PASS', flush=True)
