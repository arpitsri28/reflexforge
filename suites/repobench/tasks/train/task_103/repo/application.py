from broker import Broker
from storage import Store
from handlers import BalanceHandler
from consumer import Consumer
def build(messages):
    return Consumer(Broker(messages),Store(),BalanceHandler())
