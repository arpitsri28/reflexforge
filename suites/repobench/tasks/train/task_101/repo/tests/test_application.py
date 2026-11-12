import unittest
from gateway import Gateway
from journal import Journal
from audit import Audit
from payments import PaymentService
from api import API
class PaymentsTest(unittest.TestCase):
    def setUp(self):
        self.gateway, self.audit = Gateway(), Audit()
        self.service = PaymentService(self.gateway, Journal(), self.audit)
        self.api = API(self.service)
    def test_regular_checkout(self):
        self.assertEqual(self.api.post('a', {'key':'x','amount':25})['amount'],25)
    def test_replay(self):
        self.assertEqual(self.service.submit('a','x',25),self.service.submit('a','x',25))
    def test_lost_reply(self):
        self.gateway.lose_next_reply = True
        self.api.post('a', {'key':'x','amount':25})
        self.assertEqual(len(self.gateway.charges),1)
