import unittest
from messages import Message
from application import build
from simulation import drain
class DeliveryTest(unittest.TestCase):
    def test_normal(self):
        c=build([Message('a','u',3)])
        self.assertEqual(drain(c),['applied']);self.assertEqual(c.store.balances,{'u':3})
    def test_recover(self):
        c=build([Message('a','u',3)]);c.handler.fail_once.add('a')
        with self.assertRaises(RuntimeError): c.once()
        self.assertEqual(c.once(),'applied')
