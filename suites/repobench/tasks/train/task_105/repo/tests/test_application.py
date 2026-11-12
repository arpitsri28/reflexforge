import unittest
from application import build
from reporting import report
class LedgerTest(unittest.TestCase):
    def test_normal(self):
        s,tx,a,t=build({'a':20,'b':0});t.send('a','b',5,1)
        self.assertEqual(report(s)['balances'],{'a':14,'b':5})
    def test_failed_fee(self):
        s,tx,a,t=build({'a':20,'b':0})
        with self.assertRaises(ValueError): t.send('a','b',5,-1)
        self.assertEqual(report(s)['balances'],{'a':20,'b':0})
