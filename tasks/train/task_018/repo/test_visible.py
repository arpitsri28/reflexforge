from service import append
data = {'items': [1]}
try: append(data, 2, True)
except ValueError: pass
assert data == {'items': [1]}
