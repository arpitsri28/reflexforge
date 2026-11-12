import sys,unittest,json
sys.path.insert(0,'/workspace')
from gateway import Gateway, ReplyLost
from journal import Journal
from audit import Audit
from payments import PaymentService
from api import API
class Contract(unittest.TestCase):
    def build(self):
        g,a=Gateway(),Audit()
        return g,a,PaymentService(g,Journal(),a)
    def test_ambiguous_commit(self):
        g,a,s=self.build(); g.lose_next_reply=True
        receipt=API(s).post('u',{'key':'r','amount':73})
        self.assertEqual(receipt,s.submit('u','r',73))
        self.assertEqual(len(g.charges),1)
        self.assertEqual(len(a.events),1)
    def test_pending_conflict(self):
        g,a,s=self.build();g.lose_next_reply=True
        with self.assertRaises(ReplyLost): s.submit('u','r',73)
        with self.assertRaises(ValueError): s.submit('u','r',74)
        self.assertEqual(len(g.charges),1)
        self.assertEqual(s.submit('u','r',73)['amount'],73)
    def test_currency_conflict(self):
        g,a,s=self.build();s.submit('u','r',73)
        with self.assertRaises(ValueError): s.submit('u','r',73,'EUR')
    def test_account_scope(self):
        g,a,s=self.build();s.submit('a','x',5);s.submit('b','x',7)
        self.assertEqual(len(g.charges),2)
        self.assertEqual(len(a.for_account('a')),1)
    def test_validation_has_no_effect(self):
        g,a,s=self.build()
        with self.assertRaises(ValueError): s.submit('a','x',0)
        self.assertEqual(g.charges,{})
        self.assertEqual(a.events,[])

    def test_account_and_key_delimiters_do_not_alias(self):
        g,a,s=self.build()
        s.submit('a:b','c',5)
        s.submit('a','b:c',7)
        self.assertEqual(len(g.charges),2)

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
