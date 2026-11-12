class Checkpoint:
    def __init__(self): self.cursor=None;self.complete=False
    def advance(self,next_cursor): self.cursor=next_cursor;self.complete=next_cursor is None
    def snapshot(self): return self.cursor,self.complete
