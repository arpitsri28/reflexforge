from lru import LRU
from lookup import fetch
c = LRU(2)
c.put('a', 1)
c.put('b', 2)
assert fetch(c, 'a', lambda k: 9) == 1
c.put('c', 3)
assert 'a' in c.data and 'b' not in c.data
