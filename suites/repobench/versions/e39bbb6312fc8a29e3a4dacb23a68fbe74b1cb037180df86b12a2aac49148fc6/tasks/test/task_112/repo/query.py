from tokenization import tokens
def search(store,index,text):
    terms=tokens(text)
    if not terms: return []
    matches=set.intersection(*(set(index.postings.get(term,set())) for term in terms))
    return [store.get(key) for key in sorted(matches)]
