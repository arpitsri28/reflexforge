import asyncio
async def race_fail_fast(coroutines):
    tasks = [asyncio.create_task(c) for c in coroutines]
    return await asyncio.gather(*tasks)
