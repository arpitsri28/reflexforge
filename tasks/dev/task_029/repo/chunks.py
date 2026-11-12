def chunks(values, size):
    if size <= 0: raise ValueError('size')
    batch = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
