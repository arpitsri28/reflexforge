import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
from frames import FrameDecoder
from transport import receive
d = FrameDecoder()
assert d.feed(b'\x03a') == []
assert d.feed(b'bc\x00\x01x') == [b'abc', b'', b'x']
assert d.feed(b'') == []
assert receive(FrameDecoder(), [b'\x02', b'a', b'b\x01z']) == [b'ab', b'z']

print('REGRESSION_PASS', flush=True)
