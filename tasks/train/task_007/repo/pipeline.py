from collector import collect
async def total(items, fetch):
    values = await collect(items, fetch)
    return sum(values)
