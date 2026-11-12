from collections import OrderedDict
class LRU:
    def __init__(self, capacity):
        self.capacity, self.data = capacity, OrderedDict()
    def get(self, key):
        return self.data[key]
    def put(self, key, value):
        self.data[key] = value
        if len(self.data) > self.capacity: self.data.popitem(last=False)
