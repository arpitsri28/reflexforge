from pool import Pool
from worker import Worker
from configuration import validate_factories
class Application:
    def __init__(self,events): self.pool=Pool();self.worker=Worker(events)
    def start(self,factories): self.pool.start(validate_factories(factories));self.worker.start()
    def stop(self): self.worker.drain();self.pool.stop()
