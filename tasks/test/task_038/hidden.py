import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
import sys
import registry
assert 'builtin_plugin' not in sys.modules
registry.load_defaults()
assert registry.run('double', 4) == 8
registry.load_defaults()
assert len(registry.HANDLERS) == 1
try: registry.run('missing', 1)
except KeyError: pass
else: raise AssertionError('missing plugin accepted')

print('REGRESSION_PASS', flush=True)
