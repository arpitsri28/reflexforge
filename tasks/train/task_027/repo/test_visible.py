from batching import process
from converters import integer
try: process(['offline'], integer)
except RuntimeError: pass
else: raise AssertionError('infrastructure failure hidden')
