def report(store):
    return {'balances':dict(store.account_view()),'audit':list(store.audit_view())}
