class BalanceHandler:
    def __init__(self): self.fail_once=set()
    def apply(self,message,store):
        store.balances[message.account]=store.balances.get(message.account,0)+message.delta
        if message.key in self.fail_once:
            self.fail_once.remove(message.key)
            raise RuntimeError('interrupted handler')
        store.audit.append((message.key,message.account,message.delta))
