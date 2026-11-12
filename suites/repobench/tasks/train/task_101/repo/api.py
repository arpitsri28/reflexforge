from transport import retry
class API:
    def __init__(self, service): self.service = service
    def post(self, account, body):
        return retry(lambda: self.service.submit(account, body['key'], body['amount'], body.get('currency', 'USD')))
