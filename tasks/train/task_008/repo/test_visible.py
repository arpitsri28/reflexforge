from client import request
calls = []
def bad():
    calls.append(1)
    raise ValueError('bad request')
try: request(bad)
except ValueError: pass
assert len(calls) == 1
