import asyncio
async def run(counter, count):
    return await asyncio.gather(*(counter.increment() for _ in range(count)))
