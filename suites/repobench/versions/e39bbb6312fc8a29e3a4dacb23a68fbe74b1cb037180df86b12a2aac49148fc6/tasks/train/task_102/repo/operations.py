async def double(value): return value*2
async def reject_negative(value):
    if value<0: raise ValueError('negative input')
    return value
