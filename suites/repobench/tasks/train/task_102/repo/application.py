from broker import Broker
from results import Results
from worker import Worker
from operations import double
def build(jobs,count=2):
    broker,results=Broker(jobs),Results()
    return broker,results,[Worker(broker,results,double) for _ in range(count)]
