class Accounts:
    def __init__(self,store,transactions): self.store,self.transactions=store,transactions
    def change(self,name,amount):
        with self.transactions.begin():
            balance=self.store.data['accounts'][name]+amount
            if balance<0: raise ValueError('insufficient funds')
            self.store.data['accounts'][name]=balance
