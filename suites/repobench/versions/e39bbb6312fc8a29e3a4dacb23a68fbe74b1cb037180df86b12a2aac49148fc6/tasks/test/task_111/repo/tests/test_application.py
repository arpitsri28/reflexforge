import unittest
from definitions import Definition
from application import Application
class DependencyTest(unittest.TestCase):
    def test_normal(self):
        a=Application([Definition('v','value',options={'value':3}),Definition('app','bundle',('v',))])
        self.assertEqual(a.service('app')['services']['v']['value'],3)
    def test_retry_construction(self):
        a=Application([Definition('v','flaky')]);calls=[]
        def flaky(deps,options):
            calls.append(1)
            if len(calls)==1: raise RuntimeError('temporary')
            return {'ok':True}
        a.factories.register('flaky',flaky)
        with self.assertRaises(RuntimeError): a.service('v')
        self.assertEqual(a.service('v'),{'ok':True})
