from ordering import merge
def ids(sources): return [r['id'] for r in merge(sources)]
