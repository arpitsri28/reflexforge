from session import session
def execute(factory, operation):
    with session(factory) as connection:
        return operation(connection)
