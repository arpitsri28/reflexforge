def encode(params):
    return '&'.join(str(k) + '=' + str(v) for k, v in params.items())
