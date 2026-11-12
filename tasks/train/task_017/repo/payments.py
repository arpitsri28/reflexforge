class Payments:
    def __init__(self, charge):
        self.charge = charge
        self.receipts = {}
    def submit(self, key, amount):
        receipt = self.charge(amount)
        self.receipts[key] = (amount, receipt)
        return receipt
