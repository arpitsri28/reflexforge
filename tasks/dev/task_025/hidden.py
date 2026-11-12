import sys
sys.path.insert(0, '/workspace')
print('REGRESSION_START', flush=True)
import asyncio
from service import process
async def check():
    async def value(x): return x
    assert await process([value(2), value(1)]) == [2, 1]
    assert await process([]) == []
    started, stopped = asyncio.Event(), asyncio.Event()
    async def blocked():
        started.set()
        try: await asyncio.Event().wait()
        finally: stopped.set()
    async def fail():
        await started.wait()
        raise ValueError('failure')
    try: await process([blocked(), fail()])
    except ValueError as exc: assert str(exc) == 'failure'
    else: raise AssertionError('failure swallowed')
    assert stopped.is_set()
asyncio.run(check())

print('REGRESSION_PASS', flush=True)
