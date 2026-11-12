import unittest
from application import Application
class ConfigurationTest(unittest.TestCase):
    def test_defaults_work(self): self.assertTrue(Application().tick(10,'hello'))
    def test_cli_disables_delivery(self):
        app=Application(env={'MAIL_ENABLED':'true'},cli={'mail':{'enabled':False}})
        self.assertFalse(app.tick(10,'hello'))
