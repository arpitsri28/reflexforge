import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from directory import Directory
from ui import render
d = Directory()
assert d.listing() == []
d.put('b', 2)
d.put('a', 1)
assert render(d) == 'a,b'
d.listing().append('fake')
assert render(d) == 'a,b'
d.delete('a')
assert render(d) == 'b'

print('REGRESSION_PASS', flush=True)
