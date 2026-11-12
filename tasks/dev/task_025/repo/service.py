from group import race_fail_fast
async def process(coroutines): return await race_fail_fast(coroutines)
