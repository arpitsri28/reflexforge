from parsing import environment
from resolver import resolve
from mailer import Mailer
from scheduler import Scheduler
class Application:
    def __init__(self,file=None,env=None,cli=None):
        self.config=resolve(file or {},environment(env or {}),cli or {})
        self.mailer=Mailer(self.config['mail']);self.scheduler=Scheduler(self.config['jobs'])
    def tick(self,time,message):
        if self.scheduler.tick(time): return self.mailer.send(message)
        return False
