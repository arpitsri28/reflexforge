from validation import validate
from normalization import normalize
class Pipeline:
    def __init__(self,totals): self.totals=totals
    def ingest(self,rows):
        errors=[]
        for index,row in enumerate(rows):
            try: validate(row);normalized=normalize(row)
            except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                errors.append((index,type(exc).__name__));continue
            self.totals.add(normalized)
        return errors
