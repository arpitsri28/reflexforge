import unittest
from application import Application
from resources import Resource
from telemetry import live,close_order
class LifecycleTest(unittest.TestCase):
    def test_success(self):
        events=[];r=Resource('a',events);app=Application(events);app.start([lambda:r]);app.stop()
        self.assertEqual(live([r]),[])
    def test_partial_startup(self):
        events=[];resources=[Resource('a',events),Resource('b',events,'validate')];app=Application(events)
        with self.assertRaises(ValueError): app.start([lambda:resources[0],lambda:resources[1]])
        self.assertEqual(live(resources),[])
