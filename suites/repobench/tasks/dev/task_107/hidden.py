import sys,unittest,json
sys.path.insert(0,'/workspace')
from models import Principal,Document
from application import build
class Contract(unittest.TestCase):
    def build(self):
        return build([Principal('a','t'),Principal('b','t'),Principal('x','other',True)],
            [Document('d','t','a','secret')],{'a':'a','b':'b','x':'x'})
    def test_principal_and_tenant_boundaries(self):
        r,p,app=self.build();app.request('a','d')
        for token in ['b','x']:
            with self.assertRaises(PermissionError): app.request(token,'d')
    def test_role_revocation(self):
        r,p,app=self.build();r.roles('b',True);app.request('b','d');r.roles('b',False)
        with self.assertRaises(PermissionError): app.request('b','d')
    def test_document_change(self):
        r,p,app=self.build();r.update_document('d',public=True);app.request('b','d')
        r.update_document('d',public=False)
        with self.assertRaises(PermissionError): app.request('b','d')
    def test_decision_reuse_and_response_ownership(self):
        r,p,app=self.build();first=app.request('a','d');first['body']='changed'
        self.assertEqual(app.request('a','d')['body'],'secret');self.assertEqual(p.evaluations,1)
    def test_ownership_transfer(self):
        r,p,app=self.build();app.request('a','d');r.update_document('d',owner='b')
        with self.assertRaises(PermissionError): app.request('a','d')
        self.assertEqual(app.request('b','d')['body'],'secret')
    def test_invalid_token(self):
        r,p,app=self.build()
        with self.assertRaises(PermissionError): app.request('missing','d')

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
