import sys,unittest,json
sys.path.insert(0,'/workspace')
from application import build
from reporting import report
class Contract(unittest.TestCase):
    def test_outer_rollback_restores_inner_commits(self):
        s,tx,a,t=build({'a':20,'b':0});view=s.account_view();events=s.audit_view()
        with self.assertRaises(ValueError):
            with tx.begin(): t.send('a','b',5);raise ValueError('abort')
        self.assertEqual(view,{'a':20,'b':0});self.assertEqual(events,[])
        self.assertIs(view,s.account_view());self.assertEqual(tx.depth,0)
    def test_inner_rollback_can_be_caught(self):
        s,tx,a,t=build({'a':20,'b':0})
        with tx.begin():
            a.change('a',-2)
            try:
                with tx.begin(): a.change('a',-3);raise RuntimeError('inner')
            except RuntimeError: pass
            a.change('b',2)
        self.assertEqual(report(s)['balances'],{'a':18,'b':2})
    def test_fee_failure_is_atomic(self):
        s,tx,a,t=build({'a':20,'b':0})
        with self.assertRaises(ValueError): t.send('a','b',5,-1)
        self.assertEqual(report(s),{'balances':{'a':20,'b':0},'audit':[]})
    def test_live_views_on_simple_rollback(self):
        s,tx,a,t=build({'a':20});view=s.account_view()
        with self.assertRaises(RuntimeError):
            with tx.begin(): s.data['accounts']['a']=1;raise RuntimeError('abort')
        self.assertEqual(view['a'],20)
    def test_success_and_negative_balance(self):
        s,tx,a,t=build({'a':20,'b':0});t.send('a','b',5,1)
        self.assertEqual(report(s)['balances'],{'a':14,'b':5})
        with self.assertRaises(ValueError): a.change('a',-100)
        self.assertEqual(s.account_view()['a'],14)

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
