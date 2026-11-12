from directory import Directory
from ui import render
d = Directory()
d.put('a', 1)
assert render(d) == 'a'
d.put('b', 2)
assert render(d) == 'a,b'
