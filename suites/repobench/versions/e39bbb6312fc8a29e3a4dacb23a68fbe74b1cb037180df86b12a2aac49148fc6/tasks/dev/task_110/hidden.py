import sys,unittest,json
sys.path.insert(0,'/workspace')
import json
from stream import Stream
from encoding import encode
class Contract(unittest.TestCase):
    def event(self,seq,label='x',amount=3): return {'seq':seq,'kind':'add','amount':amount,'label':label}
    def test_every_byte_boundary(self):
        wire=encode(self.event(1));expected=[3]
        for boundary in range(len(wire)+1):
            s=Stream();self.assertEqual(s.receive(wire[:boundary])+s.receive(wire[boundary:]),expected)
    def test_unicode_byte_lengths(self):
        event=self.event(1,'café 雪');wire=encode(event)
        self.assertEqual(int.from_bytes(wire[:4],'big'),len(wire)-4)
        s=Stream();values=[]
        for byte in wire: values+=s.receive(bytes([byte]))
        self.assertEqual(values,[3]);self.assertEqual(s.router.labels,['café 雪'])
    def test_coalesced_frames_replay_and_ping(self):
        s=Stream();wire=encode(self.event(1))+encode(self.event(1))+encode({'seq':2,'kind':'ping'})+encode(self.event(3,amount=4))
        self.assertEqual(s.receive(wire),[3,3,7]);self.assertEqual(s.router.pings,1)
    def test_invalid_payload_preserves_state(self):
        s=Stream()
        with self.assertRaises(ValueError): s.receive(encode({'seq':1,'kind':'add','amount':True,'label':'x'}))
        self.assertEqual(s.session.last,0);self.assertEqual(s.router.total,0)
    def test_oversized_frame(self):
        with self.assertRaises(ValueError): Stream().receive((65537).to_bytes(4,'big'))

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
