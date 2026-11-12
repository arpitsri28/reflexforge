import sys,unittest,json
sys.path.insert(0,'/workspace')
from copy import deepcopy
from defaults import DEFAULTS
from application import Application
class Contract(unittest.TestCase):
    def test_false_and_zero(self):
        app=Application(env={'MAIL_ENABLED':'true','JOB_INTERVAL':'5'},cli={'mail':{'enabled':False},'jobs':{'interval':0}})
        self.assertFalse(app.tick(0,'no'));self.assertEqual(app.mailer.sent,[]);self.assertEqual(app.scheduler.runs,[])
    def test_precedence(self):
        app=Application(file={'mail':{'host':'file'}},env={'MAIL_HOST':'env'},cli={'mail':{'host':'cli'}})
        app.tick(10,'x');self.assertEqual(app.mailer.sent,[('cli','x')])
    def test_instances_do_not_share_state(self):
        original=deepcopy(DEFAULTS)
        a=Application(cli={'mail':{'host':'first'}});b=Application()
        a.config['mail']['tags'].append('mutated')
        self.assertEqual(b.config['mail']['host'],original['mail']['host'])
        self.assertEqual(DEFAULTS,original);self.assertEqual(b.config['mail']['tags'],['default'])
    def test_input_ownership(self):
        settings={'mail':{'tags':['custom']}}
        a=Application(cli=settings);a.config['mail']['tags'].append('later')
        self.assertEqual(settings['mail']['tags'],['custom'])
    def test_invalid_configuration(self):
        with self.assertRaises(ValueError): Application(env={'MAIL_ENABLED':'maybe'})
        with self.assertRaises(ValueError): Application(cli={'jobs':{'interval':-1}})

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
