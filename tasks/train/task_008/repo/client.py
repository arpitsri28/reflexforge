from retrying import retry
def request(operation):
    return retry(operation, 3)
