def integer(value):
    if value == 'offline': raise RuntimeError('unavailable')
    return int(value)
