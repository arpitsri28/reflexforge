from contextlib import contextmanager
@contextmanager
def transaction(data):
    original = data.copy()
    try: yield data
    except Exception:
        data.clear()
        data.update(original)
        raise
