from models import Request
class PaymentService:
    def __init__(self, gateway, journal, audit):
        self.gateway, self.journal, self.audit = gateway, journal, audit
        self.sequence = 0
    def submit(self, account, key, amount, currency='USD'):
        request = Request(account, key, amount, currency)
        request.validate()
        record = self.journal.prepare(request)
        if record.receipt is not None: return dict(record.receipt)
        self.sequence += 1
        provider_key = f'{request.account}:{request.key}:{self.sequence}'
        receipt = self.gateway.charge(provider_key, request.amount, request.currency)
        record.receipt = dict(receipt)
        self.audit.completed(request, receipt)
        return receipt
