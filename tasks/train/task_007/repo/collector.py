async def collect(items, fetch):
    return [fetch(item) for item in items]
