import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
import asyncio
from collector import collect
from pipeline import total
async def check():
    seen = []
    async def fetch(x):
        seen.append(x)
        return x * 2
    assert await collect([3, 1, 2], fetch) == [6, 2, 4]
    assert seen == [3, 1, 2]
    assert await collect([], fetch) == []
    assert await total([4], fetch) == 8
asyncio.run(check())

print('REGRESSION_PASS', flush=True)
