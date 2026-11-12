import unittest,json
from application import Application
class PipelineTest(unittest.TestCase):
    def test_json_sale(self):
        a=Application();self.assertEqual(a.json('[{"sale_id":"j","currency":"usd","timestamp":"2025-01-01T00:00:00Z","amount_cents":1250}]'),[])
        self.assertEqual(json.loads(a.report())[0]['cents'],1250)
    def test_csv_sale(self):
        a=Application();a.csv('sale_id,currency,timestamp,amount\nc,usd,2025-01-01T00:00:00Z,12.50\n'.replace('\\n','\n'))
        self.assertEqual(json.loads(a.report())[0]['cents'],1250)
