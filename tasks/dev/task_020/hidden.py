import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
import asyncio
from counter import Counter
from batch import run
async def check():
    c = Counter()
    assert sorted(await run(c, 8)) == list(range(1, 9))
    assert c.value == 8
    assert await run(c, 0) == []
    assert await c.increment() == 9
asyncio.run(check())

print('REGRESSION_PASS', flush=True)
