import sys,unittest,json
sys.path.insert(0,'/workspace')
import asyncio
from jobs import Job
from broker import Broker
from results import Results
from worker import Worker
from operations import double,reject_negative
from scheduler import tick
from application import build
class Contract(unittest.IsolatedAsyncioTestCase):
    async def test_exclusive_reservation(self):
        gate,entered=asyncio.Event(),asyncio.Event()
        async def hook(): entered.set();await gate.wait()
        job=Job('a',4);b=Broker([job],hook)
        a=asyncio.create_task(b.claim());await entered.wait()
        c=asyncio.create_task(b.claim());await asyncio.sleep(0);gate.set()
        values=await asyncio.gather(a,c)
        self.assertEqual(sum(v is not None for v in values),1)
    async def test_cancelled_acquisition_releases(self):
        entered=asyncio.Event()
        async def hook(): entered.set();await asyncio.Event().wait()
        j=Job('a',1);b=Broker([j],hook)
        task=asyncio.create_task(b.claim());await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(j.state,'queued')
    async def test_cancelled_processing_retries(self):
        entered=asyncio.Event()
        async def block(x): entered.set();await asyncio.Event().wait()
        j=Job('a',2);b=Broker([j]);r=Results();w=Worker(b,r,block)
        task=asyncio.create_task(w.once());await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(j.state,'queued');self.assertEqual(r.values,{})
        await Worker(b,r,double).once()
        self.assertEqual(j.state,'done');self.assertEqual(r.get('a'),4)
    async def test_processing_error_releases(self):
        j=Job('a',-1);b=Broker([j]);r=Results()
        with self.assertRaises(ValueError): await Worker(b,r,reject_negative).once()
        self.assertEqual(j.state,'queued')
    async def test_multiple_jobs_and_results(self):
        jobs=[Job(str(i),i) for i in range(4)];b,r,workers=build(jobs,4)
        await tick(workers)
        self.assertEqual(r.values,{str(i):i*2 for i in range(4)})
        self.assertTrue(all(j.state=='done' and j.attempts==1 for j in jobs))

suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result=unittest.TestResult()
suite.run(result)
report={'tests_run':result.testsRun,'failures':[test.id() for test,_ in result.failures],
        'errors':[test.id() for test,_ in result.errors], 'successful':result.wasSuccessful(),
        'details': [text for _,text in result.failures+result.errors]}
print('RF_QA '+json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
