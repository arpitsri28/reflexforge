from build import plan
try: plan({'a': ['b'], 'b': ['a']}, 'a')
except ValueError: pass
else: raise AssertionError('cycle accepted')
