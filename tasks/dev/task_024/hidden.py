import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from lru import LRU
from lookup import fetch
c = LRU(2)
c.put('a', 1)
c.put('b', 2)
assert fetch(c, 'a', lambda k: 9) == 1
c.put('c', 3)
assert list(c.data) == ['a', 'c']
c.put('a', 7)
assert list(c.data) == ['c', 'a'] and c.get('a') == 7
assert fetch(c, 'd', lambda k: 4) == 4
assert len(c.data) == 2

print('REGRESSION_PASS', flush=True)
