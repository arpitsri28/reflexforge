def partition(rows):
    weight = sum(w for value, w in rows)
    total = sum(value * w for value, w in rows)
    return total, weight
