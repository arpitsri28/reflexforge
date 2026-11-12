from bus import Bus
from listeners import once
b, seen = Bus(), []
once(b, lambda x: seen.append(('one', x)))
b.subscribe(lambda x: seen.append(('two', x)))
b.publish(1)
assert seen == [('one', 1), ('two', 1)]
