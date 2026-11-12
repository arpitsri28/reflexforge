def retry(operation, attempts):
    if attempts < 1: raise ValueError('attempts')
    last = None
    for _ in range(attempts):
        try: return operation()
        except Exception as exc: last = exc
    raise last
