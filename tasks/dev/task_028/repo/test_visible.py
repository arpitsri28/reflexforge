from config import resolve
assert resolve({'db': {'host': 'local', 'port': 1}}, {'db': {'port': 2}}) == {'db': {'host': 'local', 'port': 2}}
