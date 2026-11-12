class Stock:
    def __init__(self, quantity):
        self.quantity = quantity
        self.reservations = {}
    def available(self):
        return self.quantity
    def reserve(self, cart, count):
        if count <= 0 or cart in self.reservations or count > self.available():
            raise ValueError('unavailable')
        self.reservations[cart] = count
    def cancel(self, cart):
        self.reservations.pop(cart, None)
