async def noop(): pass
class Broker:
    def __init__(self, jobs, before_claim=noop):
        self.jobs=list(jobs)
        self.before_claim=before_claim
    async def claim(self):
        job=next((j for j in self.jobs if j.state=='queued'),None)
        if job is None: return None
        await self.before_claim()
        job.state = 'leased'
        return job
    def ack(self,job): job.state='done'
    def release(self,job):
        if job.state=='leased': job.state='queued'
    def pending(self): return [j.key for j in self.jobs if j.state!='done']
