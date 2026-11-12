from contextlib import contextmanager
@contextmanager
def session(factory):
    connection = factory()
    yield connection
    connection.close()
