from registry import Registry
from factories import Factories
from providers import install
from loader import Loader
class Application:
    def __init__(self,definitions):
        self.factories=Factories();install(self.factories);self.loader=Loader(Registry(definitions),self.factories)
    def service(self,name): return self.loader.resolve(name)
