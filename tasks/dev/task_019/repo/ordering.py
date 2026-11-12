def merge(sources):
    rows = [dict(row) for source in sources for row in source]
    return sorted(rows, key=lambda row: (row['priority'], row['id']), reverse=True)
