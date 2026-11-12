import unittest
from stream import Stream
from encoding import encode
class StreamTest(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(Stream().receive(encode({'seq':1,'kind':'add','amount':3,'label':'x'})),[3])
    def test_fragmented(self):
        wire=encode({'seq':1,'kind':'add','amount':3,'label':'x'});s=Stream()
        self.assertEqual(s.receive(wire[:7])+s.receive(wire[7:]),[3])
