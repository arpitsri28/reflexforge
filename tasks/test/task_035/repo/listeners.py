def once(bus, callback):
    def handler(value):
        bus.unsubscribe(handler)
        callback(value)
    bus.subscribe(handler)
