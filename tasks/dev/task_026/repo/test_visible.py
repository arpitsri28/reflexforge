from request import credentials
try: credentials({'Authorization': 'Basic abc'})
except ValueError: pass
else: raise AssertionError('wrong scheme accepted')
