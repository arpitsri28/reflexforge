from decimal import Decimal
class Money:
    def __init__(self, amount, currency):
        self.amount = Decimal(amount)
        self.currency = currency
