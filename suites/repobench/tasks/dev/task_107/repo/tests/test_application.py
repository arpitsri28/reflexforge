import unittest
from models import Principal,Document
from application import build
class AccessTest(unittest.TestCase):
    def setUp(self):
        self.r,self.p,self.app=build([Principal('owner','t'),Principal('other','t')],[Document('d','t','owner','secret')],{'a':'owner','b':'other'})
    def test_owner(self): self.assertEqual(self.app.request('a','d')['body'],'secret')
    def test_second_user_denied(self):
        self.app.request('a','d')
        with self.assertRaises(PermissionError): self.app.request('b','d')
