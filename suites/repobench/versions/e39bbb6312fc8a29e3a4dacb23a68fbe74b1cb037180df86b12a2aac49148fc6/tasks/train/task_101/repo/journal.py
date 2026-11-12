from models import Record
class Journal:
    def __init__(self): self.records = {}
    def prepare(self, request):
        key = (request.account, request.key)
        record = self.records.setdefault(key, Record(request.fingerprint))
        if record.receipt is not None and record.fingerprint != request.fingerprint:
            raise ValueError('conflicting checkout')
        return record
