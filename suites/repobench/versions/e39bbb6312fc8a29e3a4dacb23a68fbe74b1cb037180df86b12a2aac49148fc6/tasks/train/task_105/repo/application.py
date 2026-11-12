from storage import Store
from transactions import Transactions
from accounts import Accounts
from transfers import Transfers
def build(balances):
    store=Store(balances);tx=Transactions(store);accounts=Accounts(store,tx)
    return store,tx,accounts,Transfers(accounts,tx)
