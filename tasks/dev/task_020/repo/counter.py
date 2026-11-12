import asyncio
class Counter:
    def __init__(self):
        self.value = 0
        self.lock = asyncio.Lock()
    async def increment(self):
        before = self.value
        await asyncio.sleep(0)
        self.value = before + 1
        return self.value
