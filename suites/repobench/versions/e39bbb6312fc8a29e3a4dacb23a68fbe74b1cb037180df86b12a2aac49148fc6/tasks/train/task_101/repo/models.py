from dataclasses import dataclass
@dataclass(frozen=True)
class Request:
    account: str
    key: str
    amount: int
    currency: str = 'USD'
    @property
    def fingerprint(self): return (self.amount, self.currency)
    def validate(self):
        if type(self.amount) is not int or self.amount <= 0: raise ValueError('amount')
        if not self.account or not self.key or len(self.currency) != 3: raise ValueError('request')
@dataclass
class Record:
    fingerprint: tuple
    receipt: dict | None = None
