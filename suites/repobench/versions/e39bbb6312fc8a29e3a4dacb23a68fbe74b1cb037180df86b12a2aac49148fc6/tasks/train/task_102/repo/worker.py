class Worker:
    def __init__(self,broker,results,operation):
        self.broker,self.results,self.operation=broker,results,operation
    async def once(self):
        job=await self.broker.claim()
        if job is None: return None
        job.attempts+=1
        try:
            value=await self.operation(job.payload)
            self.results.put(job.key,value)
        finally:
            self.broker.ack(job)
