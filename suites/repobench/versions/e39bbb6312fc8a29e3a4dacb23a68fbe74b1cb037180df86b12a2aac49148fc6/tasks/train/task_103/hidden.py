import sys,unittest,json
sys.path.insert(0,'/workspace')
from messages import Message
from application import build
from simulation import drain
class Contract(unittest.TestCase):
    def test_failure_is_not_acknowledged(self):
        m=Message('a','u',9);c=build([m]);c.handler.fail_once.add('a')
        with self.assertRaises(RuntimeError): c.once()
        self.assertEqual(c.broker.pending,[m]);self.assertEqual(c.broker.acks,[])
        self.assertEqual(c.store.balances,{});self.assertEqual(c.store.seen,set())
        self.assertEqual(c.once(),'applied');self.assertEqual(c.store.balances,{'u':9})
    def test_successful_replay_is_deduplicated(self):
        m=Message('a','u',9);c=build([m]);c.once();c.broker.replay(m)
        self.assertEqual(c.once(),'duplicate');self.assertEqual(c.store.balances,{'u':9})
        self.assertEqual(len(c.store.audit),1);self.assertEqual(c.broker.pending,[])
    def test_ordered_effects(self):
        c=build([Message('a','u',9),Message('b','u',-2),Message('c','v',5)])
        self.assertEqual(drain(c),['applied']*3)
        self.assertEqual(c.store.balances,{'u':7,'v':5})
        self.assertEqual([x[0] for x in c.store.audit],['a','b','c'])
    def test_empty(self): self.assertEqual(build([]).once(),'empty')

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
