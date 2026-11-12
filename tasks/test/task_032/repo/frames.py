class FrameDecoder:
    def __init__(self): self.buffer = b''
    def feed(self, data):
        self.buffer += data
        result = []
        while self.buffer:
            length = self.buffer[0]
            if len(self.buffer) < length + 1:
                self.buffer = b''
                break
            result.append(self.buffer[1:length + 1])
            self.buffer = self.buffer[length + 1:]
        return result
