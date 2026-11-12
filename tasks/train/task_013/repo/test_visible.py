from summary import summarize
assert summarize(iter([2, None, 3])) == {'count': 2, 'total': 5}
