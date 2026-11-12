import unittest
from transport import Transport
from client import Client
from checkpoint import Checkpoint
from destination import Destination
from synchronizer import Synchronizer
from protocol import BatchError
class ClientTest(unittest.TestCase):
    def build(self):
        t=Transport({None:{'items':[{'id':'a','price':3}],'next':'b'},'b':{'items':[{'id':'b','price':4}],'next':None}})
        return t,Synchronizer(Client(t),Checkpoint(),Destination())
    def test_regular(self):
        t,s=self.build();self.assertEqual(s.run(),2)
    def test_resume_failure(self):
        t,s=self.build();s.sink.fail_next=True
        with self.assertRaises(BatchError): s.run()
        s.run();self.assertEqual([r['id'] for r in s.sink.export()],['a','b'])
