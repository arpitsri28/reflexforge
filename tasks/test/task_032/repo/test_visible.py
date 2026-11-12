from frames import FrameDecoder
from transport import receive
assert receive(FrameDecoder(), [b'\x03a', b'bc']) == [b'abc']
