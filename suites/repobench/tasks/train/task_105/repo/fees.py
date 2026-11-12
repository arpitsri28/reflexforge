def apply(accounts,name,fee):
    if fee<0: raise ValueError('negative fee')
    accounts.change(name,-fee)
