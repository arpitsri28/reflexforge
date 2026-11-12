from codes import Codes
from login import login
c = Codes()
c.issue('code', 'u', 10)
assert login(c, 'code', 9)['session_user'] == 'u'
assert 'code' not in c.values
