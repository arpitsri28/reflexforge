from gateway import ReplyLost
def retry(operation, attempts=2):
    if attempts < 1: raise ValueError('attempts')
    for attempt in range(attempts):
        try: return operation()
        except ReplyLost:
            if attempt+1 == attempts: raise
