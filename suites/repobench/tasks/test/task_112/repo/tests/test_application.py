import unittest
from documents import Document
from storage import Store
from indexing import Index
from service import Search
class SearchTest(unittest.TestCase):
    def test_normal(self):
        s=Search(Store(),Index());s.put(Document('a','Red apple'))
        self.assertEqual([d.key for d in s.find('APPLE')],['a'])
    def test_replacement(self):
        s=Search(Store(),Index());s.put(Document('a','Red apple'));s.put(Document('a','Blue berry'))
        self.assertEqual(s.find('red'),[])
