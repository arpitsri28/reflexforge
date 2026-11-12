class ReplyLost(TimeoutError): pass
class Gateway:
    def __init__(self):
        self.charges = {}
        self.lose_next_reply = False
    def charge(self, provider_key, amount, currency):
        if provider_key in self.charges: return dict(self.charges[provider_key])
        receipt = {'id': f'charge-{len(self.charges)+1}', 'amount': amount, 'currency': currency}
        self.charges[provider_key] = receipt
        if self.lose_next_reply:
            self.lose_next_reply = False
            raise ReplyLost('provider reply lost')
        return dict(receipt)
