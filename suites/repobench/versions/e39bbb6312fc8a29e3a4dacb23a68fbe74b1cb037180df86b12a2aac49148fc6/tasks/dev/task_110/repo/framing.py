class Decoder:
    def __init__(self): self.buffer=b''
    def feed(self,data):
        self.buffer+=data;frames=[]
        while len(self.buffer)>=4:
            length=int.from_bytes(self.buffer[:4],'big')
            if length>65536: raise ValueError('oversized frame')
            self.buffer=self.buffer[4:]
            if len(self.buffer)<length: break
            frames.append(self.buffer[:length]);self.buffer=self.buffer[length:]
        return frames
