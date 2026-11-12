class Totals:
    def __init__(self): self.seen={};self.groups={}
    def add(self,row):
        if row['id'] in self.seen:
            if self.seen[row['id']]!=row: raise ValueError('conflicting sale')
            return
        self.seen[row['id']]=dict(row)
        key=(row['day'],row['currency'])
        group=self.groups.setdefault(key,{'cents':0,'count':0})
        group['cents']+=row['cents'];group['count']+=1
    def rows(self):
        return [{'day':d,'currency':c,**self.groups[d,c]} for d,c in sorted(self.groups)]
