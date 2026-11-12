class Consumer:
    def __init__(self,broker,store,handler): self.broker,self.store,self.handler=broker,store,handler
    def once(self):
        message=self.broker.receive()
        if message is None: return 'empty'
        self.broker.ack(message)
        if message.key in self.store.seen: return 'duplicate'
        self.store.seen.add(message.key)
        with self.store.atomic():
            self.handler.apply(message,self.store)
        return 'applied'
