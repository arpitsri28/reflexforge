import asyncio
async def tick(workers): return await asyncio.gather(*(w.once() for w in workers))
