import sys,unittest,json
sys.path.insert(0,'/workspace')
from documents import Document
from storage import Store
from indexing import Index
from service import Search
class Contract(unittest.TestCase):
    def build(self): return Search(Store(),Index())
    def test_replace_repairs_all_projections(self):
        s=self.build();s.put(Document('a','Red apple'));s.put(Document('a','Blue berry'))
        self.assertEqual(s.find('red'),[]);self.assertNotIn('red',s.index.postings)
        self.assertEqual(s.facets(),{'berry':1,'blue':1})
    def test_invalid_edit_is_atomic(self):
        s=self.build();original=Document('a','Red apple');s.put(original)
        with self.assertRaises(ValueError): s.put(Document('a',''))
        self.assertEqual(s.store.get('a'),original);self.assertEqual(s.facets(),{'apple':1,'red':1})
    def test_delete_after_update(self):
        s=self.build();s.put(Document('a','red'));s.put(Document('a','blue'));s.delete('a')
        self.assertEqual(s.facets(),{});self.assertEqual(s.index.document_terms,{})
        self.assertEqual(s.find('red'),[]);self.assertEqual(s.find('blue'),[])
    def test_intersection_and_document_counts(self):
        s=self.build();s.put(Document('b','red apple apple'));s.put(Document('a','red berry'))
        self.assertEqual([d.key for d in s.find('red')],['a','b'])
        self.assertEqual([d.key for d in s.find('red apple')],['b']);self.assertEqual(s.facets()['apple'],1)
    def test_empty_and_missing_delete(self):
        s=self.build();s.delete('missing');self.assertEqual(s.find(''),[]);self.assertEqual(s.facets(),{})

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
