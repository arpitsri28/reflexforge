from contextlib import contextmanager
@contextmanager
def open_all(factories):
    opened = [factory() for factory in factories]
    try: yield opened
    finally:
        for resource in opened: resource.close()
