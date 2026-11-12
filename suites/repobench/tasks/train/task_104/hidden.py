import sys,unittest,json
sys.path.insert(0,'/workspace')
import json
from application import Application
def row(key='a',**changes):
    return {'sale_id':key,'currency':'usd','timestamp':'2025-01-01T00:30:00+02:00','amount_cents':1250,**changes}
class Contract(unittest.TestCase):
    def test_cross_source_equivalence(self):
        a=Application();a.csv('sale_id,currency,timestamp,amount\na,usd,2025-01-01T00:30:00+02:00,12.50\n')
        a.json(json.dumps([row()]))
        self.assertEqual(json.loads(a.report()),[{'day':'2024-12-31','currency':'USD','cents':1250,'count':1}])
    def test_type_validation(self):
        a=Application()
        errors=a.json(json.dumps([row('a',amount_cents=True),row('b',amount_cents=1.5),row('c',amount_cents='12')]))
        self.assertEqual(len(errors),3);self.assertEqual(json.loads(a.report()),[])
    def test_partition_invariance(self):
        a,b=Application(),Application();rows=[row('a'),row('b',amount_cents=30),row('c',currency='eur',amount_cents=0)]
        a.json(json.dumps(rows));b.json(json.dumps(rows[:1]));b.json(json.dumps(rows[1:]))
        self.assertEqual(a.report(),b.report())
    def test_conflict(self):
        a=Application();a.json(json.dumps([row()]))
        with self.assertRaises(ValueError): a.json(json.dumps([row(amount_cents=99)]))
    def test_invalid_currency_timezone_and_precision(self):
        a=Application()
        self.assertEqual(len(a.json(json.dumps([row(currency='x'),row(timestamp='2025-01-01')]))),2)
        errors=a.csv('sale_id,currency,timestamp,amount\nx,usd,2025-01-01T00:00:00Z,1.001\n')
        self.assertEqual(len(errors),1);self.assertEqual(json.loads(a.report()),[])

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
