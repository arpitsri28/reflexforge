import sys,unittest,json
sys.path.insert(0,'/workspace')
from application import Application
from resources import Resource
from telemetry import live,close_order
class Contract(unittest.TestCase):
    def test_partial_validation_cleanup(self):
        events=[];a,b=Resource('a',events),Resource('b',events,'validate');app=Application(events)
        with self.assertRaisesRegex(ValueError,'validate b'): app.start([lambda:a,lambda:b])
        self.assertEqual(close_order(events),['b','a']);self.assertEqual(live([a,b]),[])
        self.assertEqual(app.pool.state,'stopped');self.assertFalse(app.worker.running)
    def test_open_failure_and_restart(self):
        events=[];bad=Resource('bad',events,'open');app=Application(events)
        with self.assertRaises(ValueError): app.start([lambda:bad])
        self.assertTrue(bad.closed)
        good=Resource('good',events);app.start([lambda:good]);app.stop();self.assertTrue(good.closed)
    def test_cleanup_failure_preserves_original(self):
        events=[];a=Resource('a',events);b=Resource('b',events,'close');c=Resource('c',events,'validate');app=Application(events)
        with self.assertRaisesRegex(ValueError,'validate c'): app.start([lambda:a,lambda:b,lambda:c])
        self.assertEqual(close_order(events),['c','b','a'])
        self.assertEqual(app.pool.errors,['close b']);self.assertEqual(live([a,b,c]),[])
    def test_shutdown_order_and_idempotence(self):
        events=[];a=Resource('a',events);app=Application(events);app.start([lambda:a]);app.stop();app.stop()
        self.assertLess(events.index(('worker','drain')),events.index(('close','a')))
        self.assertEqual(close_order(events),['a'])
    def test_factory_failure(self):
        events=[];a=Resource('a',events);app=Application(events)
        def fail(): raise ValueError('factory')
        with self.assertRaises(ValueError): app.start([lambda:a,fail])
        self.assertTrue(a.closed);self.assertEqual(app.pool.state,'stopped')

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
