import asyncio
from service import process
async def check():
    started, stopped = asyncio.Event(), asyncio.Event()
    async def blocked():
        started.set()
        try: await asyncio.Event().wait()
        finally: stopped.set()
    async def fail():
        await started.wait()
        raise ValueError('failure')
    try: await process([blocked(), fail()])
    except ValueError: pass
    assert stopped.is_set()
asyncio.run(check())
