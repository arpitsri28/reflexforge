from transactions import transaction
def append(data, value, fail=False):
    with transaction(data):
        data['items'].append(value)
        if fail: raise ValueError('rollback')
    return data
