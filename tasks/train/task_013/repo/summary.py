from cleaning import clean
def summarize(values):
    selected = clean(values)
    count = sum(1 for _ in selected)
    return {'count': count, 'total': sum(selected)}
