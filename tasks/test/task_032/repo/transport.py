def receive(decoder, pieces):
    return [frame for piece in pieces for frame in decoder.feed(piece)]
