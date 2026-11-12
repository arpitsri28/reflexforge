from protocol import BatchError
class Destination:
    def __init__(self): self.rows={};self.fail_next=False
    def apply(self,products):
        staged=dict(self.rows)
        for product in products: staged[product['id']]=dict(product)
        if self.fail_next:
            self.fail_next=False;raise BatchError('destination unavailable')
        self.rows=staged
    def export(self): return [self.rows[key] for key in sorted(self.rows)]
