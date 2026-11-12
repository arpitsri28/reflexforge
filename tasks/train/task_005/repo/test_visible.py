from cache import ProfileCache
from profiles import load_profile
c = ProfileCache()
c.get('red', '42', load_profile)
assert c.get('blue', '42', load_profile)['tenant'] == 'blue'
