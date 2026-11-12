from fees import apply
class Transfers:
    def __init__(self,accounts,transactions): self.accounts,self.transactions=accounts,transactions
    def send(self,source,target,amount,fee=0):
        if amount<=0: raise ValueError('amount')
        with self.transactions.begin() as store:
            self.accounts.change(source,-amount)
            self.accounts.change(target,amount)
            apply(self.accounts,source,fee)
            store.data['audit'].append((source,target,amount,fee))
