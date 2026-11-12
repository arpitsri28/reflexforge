import asyncio
from counter import Counter
from batch import run
async def check():
    c = Counter()
    await run(c, 5)
    assert c.value == 5
asyncio.run(check())
