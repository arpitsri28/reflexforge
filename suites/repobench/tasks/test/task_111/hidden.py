import sys,unittest,json
sys.path.insert(0,'/workspace')
from definitions import Definition
from application import Application
from errors import DependencyCycle
class Contract(unittest.TestCase):
    def test_failed_construction_retries(self):
        a=Application([Definition('v','flaky')]);calls=[]
        def flaky(deps,options):
            calls.append(1)
            if len(calls)==1: raise RuntimeError('temporary')
            return object()
        a.factories.register('flaky',flaky)
        with self.assertRaises(RuntimeError): a.service('v')
        value=a.service('v');self.assertIsNotNone(value);self.assertIs(a.service('v'),value);self.assertEqual(len(calls),2)
    def test_cycle_path_and_recovery(self):
        a=Application([Definition('a','bundle',('b',)),Definition('b','bundle',('a',)),Definition('good','value',options={'value':7})])
        with self.assertRaises(DependencyCycle) as caught: a.service('a')
        self.assertEqual(caught.exception.path,('a','b','a'))
        self.assertEqual(a.loader.active,[]);self.assertEqual(a.service('good'),{'value':7})
        with self.assertRaises(DependencyCycle): a.service('a')
    def test_shared_diamond(self):
        a=Application([Definition('v','value',options={'value':3}),Definition('left','bundle',('v',)),Definition('right','bundle',('v',)),Definition('root','bundle',('left','right'))])
        root=a.service('root')['services']
        self.assertIs(root['left']['services']['v'],root['right']['services']['v']);self.assertEqual(a.factories.calls['value'],1)
    def test_unknown_name_not_cached(self):
        a=Application([])
        for _ in range(2):
            with self.assertRaises(KeyError): a.service('unknown')
        self.assertEqual(a.loader.instances,{})
    def test_options_and_application_isolation(self):
        options={'value':['original']};d=Definition('v','value',options=options)
        a,b=Application([d]),Application([d]);a.service('v')['value'].append('changed')
        self.assertEqual(options,{'value':['original']});self.assertEqual(b.service('v'),{'value':['original']})

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
