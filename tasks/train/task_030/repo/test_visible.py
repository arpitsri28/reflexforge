from job import run
closed = []
class R:
    def __init__(self, name): self.name = name
    def close(self): closed.append(self.name)
run([lambda: R('a'), lambda: R('b')], lambda rs: len(rs))
assert closed == ['b', 'a']
