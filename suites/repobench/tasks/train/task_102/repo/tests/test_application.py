import asyncio,unittest
from jobs import Job
from broker import Broker
from results import Results
from worker import Worker
from application import build
from scheduler import tick
class QueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_normal(self):
        b,r,workers=build([Job('a',3)],1)
        await tick(workers)
        self.assertEqual(r.get('a'),6)
        self.assertEqual(b.pending(),[])
    async def test_parallel_claims(self):
        gate,entered=asyncio.Event(),asyncio.Event()
        async def hook(): entered.set();await gate.wait()
        job=Job('a',3);b=Broker([job],hook)
        first=asyncio.create_task(b.claim());await entered.wait()
        second=asyncio.create_task(b.claim());await asyncio.sleep(0)
        gate.set();a,c=await asyncio.gather(first,second)
        self.assertEqual(sum(x is not None for x in [a,c]),1)
