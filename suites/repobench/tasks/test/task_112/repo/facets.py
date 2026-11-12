def counts(index): return {term:len(keys) for term,keys in sorted(index.postings.items())}
def vocabulary(index): return tuple(sorted(index.postings))
