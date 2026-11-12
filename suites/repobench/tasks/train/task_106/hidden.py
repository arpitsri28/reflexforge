import sys,unittest,json
sys.path.insert(0,'/workspace')
from transport import Transport
from client import Client
from checkpoint import Checkpoint
from destination import Destination
from synchronizer import Synchronizer
from protocol import BatchError,HTTPError
class Contract(unittest.TestCase):
    def build(self):
        t=Transport({None:{'items':[{'id':'a','price':3}],'next':'b'},'b':{'items':[{'id':'b','price':4}],'next':None}})
        return t,Synchronizer(Client(t),Checkpoint(),Destination())
    def test_failed_batch_does_not_advance(self):
        t,s=self.build();s.sink.fail_next=True
        with self.assertRaises(BatchError): s.run()
        self.assertEqual(s.checkpoint.snapshot(),(None,False));self.assertEqual(s.sink.export(),[])
        self.assertEqual(s.run(),2)
    def test_invalid_page_keeps_checkpoint(self):
        t,s=self.build();t.pages[None]={'items':[{'id':7,'price':3}],'next':'b'}
        with self.assertRaises(ValueError): s.run()
        self.assertEqual(s.checkpoint.snapshot(),(None,False))
    def test_retry_same_cursor(self):
        t,s=self.build();t.failures[None]=1;s.run()
        self.assertEqual(t.requests,[None,None,'b']);self.assertEqual(len(s.sink.export()),2)
    def test_partial_resume_and_completion(self):
        t,s=self.build();self.assertEqual(s.run(max_pages=1),1)
        self.assertEqual(s.checkpoint.snapshot(),('b',False));self.assertEqual(s.run(),1)
        self.assertTrue(s.checkpoint.complete);self.assertEqual(s.run(),0)
    def test_exhausted_transport_keeps_state(self):
        t,s=self.build();t.failures[None]=3
        with self.assertRaises(HTTPError): s.run()
        self.assertEqual(s.checkpoint.snapshot(),(None,False));self.assertEqual(s.sink.export(),[])

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
