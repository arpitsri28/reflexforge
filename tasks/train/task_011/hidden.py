import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from service import authorize
from policy import can_edit
doc = {'org': 'a', 'owner': 1, 'id': 'doc'}
assert authorize({'org': 'a', 'id': 1, 'admin': False}, doc) == 'doc'
assert can_edit({'org': 'a', 'id': 2, 'admin': True}, doc)
assert not can_edit({'org': 'b', 'id': 1, 'admin': True}, doc)
assert not can_edit({'org': 'a', 'id': 2, 'admin': False}, doc)

print('REGRESSION_PASS', flush=True)
