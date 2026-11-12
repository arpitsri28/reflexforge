import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from bus import Bus
from listeners import once
b, seen = Bus(), []
once(b, lambda x: seen.append(('one', x)))
b.subscribe(lambda x: seen.append(('two', x)))
b.publish(1)
b.publish(2)
assert seen == [('one', 1), ('two', 1), ('two', 2)]
b = Bus()
seen = []
def later(x): seen.append(x)
def adding(x): b.subscribe(later)
b.subscribe(adding)
b.publish(3)
assert seen == []
b.publish(4)
assert seen == [4]
b.unsubscribe(lambda x: None)

print('REGRESSION_PASS', flush=True)
