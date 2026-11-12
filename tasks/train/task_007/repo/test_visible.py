import asyncio
from pipeline import total
async def fetch(x): return x * 2
assert asyncio.run(total([1, 2], fetch)) == 6
