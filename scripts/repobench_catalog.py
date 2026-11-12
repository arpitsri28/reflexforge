"""Private authoring data for project-authored repository-level fixtures.

Source strings are materialized, never executed on the host. Public descriptions
contain symptoms/contracts; explanations and overlays remain controller-side.
"""

from textwrap import dedent

CASES = []


def case(
    number,
    domain,
    issue,
    contract,
    modules,
    changes,
    visible,
    hidden,
    root_cause,
    dependency_path,
    invariants,
    mutant_changes,
    roles,
):
    original = {name: dedent(code).lstrip("\n") for name, code in modules.items()}

    def overlay(edits):
        files = dict(original)
        for name, before, after in edits:
            if before not in files[name]:
                raise ValueError(f"{number}: missing replacement in {name}")
            files[name] = files[name].replace(before, after)
        return {n: c for n, c in files.items() if c != original[n]}

    CASES.append(
        dict(
            number=number,
            domain=domain,
            issue=issue,
            contract=dedent(contract).strip(),
            modules=original,
            reference=overlay(changes),
            mutant=overlay(mutant_changes),
            visible=dedent(visible).lstrip("\n"),
            hidden=dedent(hidden).lstrip("\n"),
            root_cause=root_cause,
            dependency_path=dependency_path,
            invariants=invariants,
            roles=roles,
        )
    )


PAYMENT_KEY = (
    "payments.py",
    "provider_key = f'{request.account}:{request.key}:{self.sequence}'",
    "provider_key = (request.account, request.key)",
)
PENDING_CHECK = (
    "journal.py",
    "if record.receipt is not None and record.fingerprint != request.fingerprint:",
    "if record.fingerprint != request.fingerprint:",
)
case(
    101,
    "backend-payments",
    "A checkout can be charged twice after the client retries a request whose response was lost. "
    "Reusing a checkout key with different payment details must be rejected, including after a timeout.",
    """PaymentService exposes submit(account, key, amount, currency='USD') through API.post().
 Amounts are positive integer minor units. A checkout key is scoped to an account. Identical
 retries return the same receipt and perform one provider charge. A different amount or
 currency under an existing key raises ValueError. ReplyLost means the provider may have
 accepted the charge; it is the only automatically retryable error. Failed validation must
 not allocate a charge. Audit records describe successful logical checkouts once each.""",
    {
        "models.py": """
    from dataclasses import dataclass
    @dataclass(frozen=True)
    class Request:
        account: str
        key: str
        amount: int
        currency: str = 'USD'
        @property
        def fingerprint(self): return (self.amount, self.currency)
        def validate(self):
            if type(self.amount) is not int or self.amount <= 0: raise ValueError('amount')
            if not self.account or not self.key or len(self.currency) != 3: raise ValueError('request')
    @dataclass
    class Record:
        fingerprint: tuple
        receipt: dict | None = None
    """,
        "journal.py": """
    from models import Record
    class Journal:
        def __init__(self): self.records = {}
        def prepare(self, request):
            key = (request.account, request.key)
            record = self.records.setdefault(key, Record(request.fingerprint))
            if record.receipt is not None and record.fingerprint != request.fingerprint:
                raise ValueError('conflicting checkout')
            return record
    """,
        "gateway.py": """
    class ReplyLost(TimeoutError): pass
    class Gateway:
        def __init__(self):
            self.charges = {}
            self.lose_next_reply = False
        def charge(self, provider_key, amount, currency):
            if provider_key in self.charges: return dict(self.charges[provider_key])
            receipt = {'id': f'charge-{len(self.charges)+1}', 'amount': amount, 'currency': currency}
            self.charges[provider_key] = receipt
            if self.lose_next_reply:
                self.lose_next_reply = False
                raise ReplyLost('provider reply lost')
            return dict(receipt)
    """,
        "audit.py": """
    class Audit:
        def __init__(self): self.events = []
        def completed(self, request, receipt):
            self.events.append((request.account, request.key, receipt['id']))
        def for_account(self, account): return [e for e in self.events if e[0] == account]
    """,
        "payments.py": """
    from models import Request
    class PaymentService:
        def __init__(self, gateway, journal, audit):
            self.gateway, self.journal, self.audit = gateway, journal, audit
            self.sequence = 0
        def submit(self, account, key, amount, currency='USD'):
            request = Request(account, key, amount, currency)
            request.validate()
            record = self.journal.prepare(request)
            if record.receipt is not None: return dict(record.receipt)
            self.sequence += 1
            provider_key = f'{request.account}:{request.key}:{self.sequence}'
            receipt = self.gateway.charge(provider_key, request.amount, request.currency)
            record.receipt = dict(receipt)
            self.audit.completed(request, receipt)
            return receipt
    """,
        "transport.py": """
    from gateway import ReplyLost
    def retry(operation, attempts=2):
        if attempts < 1: raise ValueError('attempts')
        for attempt in range(attempts):
            try: return operation()
            except ReplyLost:
                if attempt+1 == attempts: raise
    """,
        "api.py": """
    from transport import retry
    class API:
        def __init__(self, service): self.service = service
        def post(self, account, body):
            return retry(lambda: self.service.submit(account, body['key'], body['amount'], body.get('currency', 'USD')))
    """,
    },
    [PAYMENT_KEY, PENDING_CHECK],
    r"""import unittest
from gateway import Gateway
from journal import Journal
from audit import Audit
from payments import PaymentService
from api import API
class PaymentsTest(unittest.TestCase):
    def setUp(self):
        self.gateway, self.audit = Gateway(), Audit()
        self.service = PaymentService(self.gateway, Journal(), self.audit)
        self.api = API(self.service)
    def test_regular_checkout(self):
        self.assertEqual(self.api.post('a', {'key':'x','amount':25})['amount'],25)
    def test_replay(self):
        self.assertEqual(self.service.submit('a','x',25),self.service.submit('a','x',25))
    def test_lost_reply(self):
        self.gateway.lose_next_reply = True
        self.api.post('a', {'key':'x','amount':25})
        self.assertEqual(len(self.gateway.charges),1)
""",
    r"""from gateway import Gateway, ReplyLost
from journal import Journal
from audit import Audit
from payments import PaymentService
from api import API
class Contract(unittest.TestCase):
    def build(self):
        g,a=Gateway(),Audit()
        return g,a,PaymentService(g,Journal(),a)
    def test_ambiguous_commit(self):
        g,a,s=self.build(); g.lose_next_reply=True
        receipt=API(s).post('u',{'key':'r','amount':73})
        self.assertEqual(receipt,s.submit('u','r',73))
        self.assertEqual(len(g.charges),1)
        self.assertEqual(len(a.events),1)
    def test_pending_conflict(self):
        g,a,s=self.build();g.lose_next_reply=True
        with self.assertRaises(ReplyLost): s.submit('u','r',73)
        with self.assertRaises(ValueError): s.submit('u','r',74)
        self.assertEqual(len(g.charges),1)
        self.assertEqual(s.submit('u','r',73)['amount'],73)
    def test_currency_conflict(self):
        g,a,s=self.build();s.submit('u','r',73)
        with self.assertRaises(ValueError): s.submit('u','r',73,'EUR')
    def test_account_scope(self):
        g,a,s=self.build();s.submit('a','x',5);s.submit('b','x',7)
        self.assertEqual(len(g.charges),2)
        self.assertEqual(len(a.for_account('a')),1)
    def test_validation_has_no_effect(self):
        g,a,s=self.build()
        with self.assertRaises(ValueError): s.submit('a','x',0)
        self.assertEqual(g.charges,{})
        self.assertEqual(a.events,[])
""",
    "The service assigns an attempt-specific provider key after preparing a pending journal row. "
    "A committed-but-unobserved provider charge is repeated; the journal also validates payloads only after a receipt exists.",
    ["api.py", "transport.py", "payments.py", "journal.py", "gateway.py"],
    [
        "one provider effect per logical key",
        "pending and complete payload identity",
        "account isolation",
        "one audit event",
    ],
    [PAYMENT_KEY],
    {
        "models.py": "Validated request and durable receipt state",
        "journal.py": "Logical checkout identity and replay records",
        "gateway.py": "Deterministic external commit/reply-loss simulation",
        "audit.py": "Logical business-event ledger",
        "payments.py": "Coordinates requests, provider effects and journal completion",
        "transport.py": "Bounded transport retry semantics",
        "api.py": "Public request adapter",
    },
)

CLAIM_FIX = (
    "broker.py",
    "await self.before_claim()\n        job.state = 'leased'\n        return job",
    "job.state = 'leased'\n        try:\n            await self.before_claim()\n            return job\n        except BaseException:\n            job.state = 'queued'\n            raise",
)
CANCEL_FIX = (
    "worker.py",
    "finally:\n            self.broker.ack(job)",
    "except BaseException:\n            self.broker.release(job)\n            raise\n        else:\n            self.broker.ack(job)\n            return job.key",
)
case(
    102,
    "async-job-ownership",
    "Concurrent background workers sometimes process the same queued job, and cancelling an in-flight worker "
    "can make an unfinished job disappear. Successful jobs must retain their recorded results.",
    """Jobs transition queued -> leased -> done; cancellation or processing failure makes an unfinished job
 available again. At most one live worker owns a job. The before_claim hook is an instrumentation
 scheduling point and may await; keep it functional. Results are keyed by job ID and successful
 processing is acknowledged after the result is stored. No wall-clock sleeps are needed for tests.""",
    {
        "jobs.py": """
    from dataclasses import dataclass
    @dataclass
    class Job:
        key: str
        payload: int
        state: str = 'queued'
        attempts: int = 0
    """,
        "broker.py": """
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
    """,
        "results.py": """
    class Results:
        def __init__(self): self.values={}
        def put(self,key,value): self.values[key]=value
        def get(self,key): return self.values[key]
    """,
        "worker.py": """
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
    """,
        "operations.py": """
    async def double(value): return value*2
    async def reject_negative(value):
        if value<0: raise ValueError('negative input')
        return value
    """,
        "scheduler.py": """
    import asyncio
    async def tick(workers): return await asyncio.gather(*(w.once() for w in workers))
    """,
        "application.py": """
    from broker import Broker
    from results import Results
    from worker import Worker
    from operations import double
    def build(jobs,count=2):
        broker,results=Broker(jobs),Results()
        return broker,results,[Worker(broker,results,double) for _ in range(count)]
    """,
    },
    [CLAIM_FIX, CANCEL_FIX],
    r"""import asyncio,unittest
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
""",
    r"""import asyncio
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
""",
    "Ownership is published after an await, allowing two claims, while unconditional acknowledgement converts cancelled work to done.",
    ["application.py", "scheduler.py", "worker.py", "broker.py", "jobs.py", "results.py"],
    [
        "exclusive ownership",
        "cancelled acquisition is available again",
        "only durable results acknowledged",
        "failure preserves retryability",
    ],
    [CLAIM_FIX],
    {
        "jobs.py": "Queue state model",
        "broker.py": "Ownership and acknowledgement transitions",
        "results.py": "Result persistence",
        "worker.py": "Processing and failure cleanup",
        "operations.py": "Business operations",
        "scheduler.py": "Concurrent worker scheduling",
        "application.py": "Public composition and construction",
    },
)

DELIVERY_FIX = (
    "consumer.py",
    "self.broker.ack(message)\n        if message.key in self.store.seen: return 'duplicate'\n        self.store.seen.add(message.key)\n        with self.store.atomic():\n            self.handler.apply(message,self.store)\n        return 'applied'",
    "if message.key in self.store.seen:\n            self.broker.ack(message)\n            return 'duplicate'\n        with self.store.atomic():\n            self.handler.apply(message,self.store)\n            self.store.seen.add(message.key)\n        self.broker.ack(message)\n        return 'applied'",
)
case(
    103,
    "message-delivery",
    "A local event consumer occasionally loses a balance update when processing fails and delivery is retried. "
    "Replayed successful messages must not apply the same business effect twice.",
    """The broker supplies at-least-once delivery. Unacknowledged messages may be redelivered; acknowledged
 messages are removed. An event key identifies one logical balance delta. Applying the delta and recording
 its processed identity must succeed together. Handler failures propagate; retrying the same message
 after recovery must work. The simulation is entirely local and exposes deterministic failure injection.""",
    {
        "messages.py": """
    from dataclasses import dataclass
    @dataclass(frozen=True)
    class Message:
        key: str
        account: str
        delta: int
    """,
        "broker.py": """
    class Broker:
        def __init__(self,messages): self.pending=list(messages);self.acks=[]
        def receive(self): return self.pending[0] if self.pending else None
        def ack(self,message):
            if message in self.pending: self.pending.remove(message)
            self.acks.append(message.key)
        def replay(self,message): self.pending.append(message)
    """,
        "storage.py": """
    from contextlib import contextmanager
    from copy import deepcopy
    class Store:
        def __init__(self): self.balances={};self.seen=set();self.audit=[]
        @contextmanager
        def atomic(self):
            before=deepcopy((self.balances,self.seen,self.audit))
            try: yield self
            except BaseException:
                self.balances,self.seen,self.audit=before
                raise
    """,
        "handlers.py": """
    class BalanceHandler:
        def __init__(self): self.fail_once=set()
        def apply(self,message,store):
            store.balances[message.account]=store.balances.get(message.account,0)+message.delta
            if message.key in self.fail_once:
                self.fail_once.remove(message.key)
                raise RuntimeError('interrupted handler')
            store.audit.append((message.key,message.account,message.delta))
    """,
        "consumer.py": """
    class Consumer:
        def __init__(self,broker,store,handler): self.broker,self.store,self.handler=broker,store,handler
        def once(self):
            message=self.broker.receive()
            if message is None: return 'empty'
            self.broker.ack(message)
            if message.key in self.store.seen: return 'duplicate'
            self.store.seen.add(message.key)
            with self.store.atomic():
                self.handler.apply(message,self.store)
            return 'applied'
    """,
        "simulation.py": """
    def drain(consumer):
        outcomes=[]
        while consumer.broker.pending: outcomes.append(consumer.once())
        return outcomes
    """,
        "application.py": """
    from broker import Broker
    from storage import Store
    from handlers import BalanceHandler
    from consumer import Consumer
    def build(messages):
        return Consumer(Broker(messages),Store(),BalanceHandler())
    """,
    },
    [DELIVERY_FIX],
    r"""import unittest
from messages import Message
from application import build
from simulation import drain
class DeliveryTest(unittest.TestCase):
    def test_normal(self):
        c=build([Message('a','u',3)])
        self.assertEqual(drain(c),['applied']);self.assertEqual(c.store.balances,{'u':3})
    def test_recover(self):
        c=build([Message('a','u',3)]);c.handler.fail_once.add('a')
        with self.assertRaises(RuntimeError): c.once()
        self.assertEqual(c.once(),'applied')
""",
    r"""from messages import Message
from application import build
from simulation import drain
class Contract(unittest.TestCase):
    def test_failure_is_not_acknowledged(self):
        m=Message('a','u',9);c=build([m]);c.handler.fail_once.add('a')
        with self.assertRaises(RuntimeError): c.once()
        self.assertEqual(c.broker.pending,[m]);self.assertEqual(c.broker.acks,[])
        self.assertEqual(c.store.balances,{});self.assertEqual(c.store.seen,set())
        self.assertEqual(c.once(),'applied');self.assertEqual(c.store.balances,{'u':9})
    def test_successful_replay_is_deduplicated(self):
        m=Message('a','u',9);c=build([m]);c.once();c.broker.replay(m)
        self.assertEqual(c.once(),'duplicate');self.assertEqual(c.store.balances,{'u':9})
        self.assertEqual(len(c.store.audit),1)
    def test_ordered_effects(self):
        c=build([Message('a','u',9),Message('b','u',-2),Message('c','v',5)])
        self.assertEqual(drain(c),['applied']*3)
        self.assertEqual(c.store.balances,{'u':7,'v':5})
        self.assertEqual([x[0] for x in c.store.audit],['a','b','c'])
    def test_empty(self): self.assertEqual(build([]).once(),'empty')
""",
    "Acknowledgement precedes the business transaction and the deduplication marker is written outside rollback ownership.",
    ["simulation.py", "consumer.py", "broker.py", "storage.py", "handlers.py"],
    [
        "ack follows successful durable effect",
        "dedup marker and effect share a transaction",
        "failure remains deliverable",
        "ordered once-only effects",
    ],
    [
        ("consumer.py", "self.broker.ack(message)\n        if message.key", "if message.key"),
        (
            "consumer.py",
            "        return 'applied'",
            "        self.broker.ack(message)\n        return 'applied'",
        ),
    ],
    {
        "messages.py": "Delivery identity and account payload",
        "broker.py": "At-least-once local delivery",
        "storage.py": "Transactional business state",
        "handlers.py": "Effect application and deterministic interruption",
        "consumer.py": "Delivery/transaction coordinator",
        "simulation.py": "Deterministic drain loop",
        "application.py": "Service construction",
    },
)

NORMALIZE_FIX = (
    "normalization.py",
    "amount=int(row.get('amount_cents',row.get('amount',0)))",
    "amount=(int(row['amount_cents']) if 'amount_cents' in row else int(Decimal(row['amount'])*100))",
)
STRICT_JSON = (
    "validation.py",
    "if 'amount_cents' in row and int(row['amount_cents']) < 0: raise ValueError('amount')",
    "if 'amount_cents' in row and (type(row['amount_cents']) is not int or row['amount_cents'] < 0): raise ValueError('amount')",
)
case(
    104,
    "mixed-source-etl",
    "Daily revenue exports disagree when the same sales arrive through CSV and JSON ingestion. Some invalid "
    "JSON amounts are accepted, and changing the input source changes the reported totals.",
    """The pipeline accepts CSV rows with amount as an exact two-decimal major-unit string, or JSON rows
 with amount_cents as a nonnegative integer (booleans are invalid). sale_id is unique per logical sale.
 Currency codes are case-insensitive and are emitted uppercase. Timestamps require an ISO timezone and
 daily buckets use UTC. Duplicates across sources count once; conflicting duplicates raise ValueError.
 Invalid rows are returned as indexed errors and do not contribute to totals. Export amounts are integer
 minor units. Processing several batches must agree with processing their concatenation.""",
    {
        "sources.py": """
    import csv,io,json
    def csv_rows(text): return list(csv.DictReader(io.StringIO(text)))
    def json_rows(text): return json.loads(text)
    """,
        "validation.py": """
    from decimal import Decimal
    from datetime import datetime
    def validate(row):
        for key in ('sale_id','currency','timestamp'):
            if not isinstance(row.get(key),str) or not row[key]: raise ValueError(key)
        if len(row['currency'])!=3: raise ValueError('currency')
        if datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).tzinfo is None: raise ValueError('timezone')
        if 'amount_cents' in row and int(row['amount_cents']) < 0: raise ValueError('amount')
        if 'amount_cents' not in row:
            amount=Decimal(row['amount'])
            if not amount.is_finite() or amount<0 or amount*100!=int(amount*100): raise ValueError('amount')
    """,
        "normalization.py": """
    from datetime import datetime,timezone
    from decimal import Decimal
    def normalize(row):
        amount=int(row.get('amount_cents',row.get('amount',0)))
        day=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).astimezone(timezone.utc).date().isoformat()
        return {'id':row['sale_id'],'day':day,'currency':row['currency'].upper(),'cents':amount}
    """,
        "aggregation.py": """
    class Totals:
        def __init__(self): self.seen={};self.groups={}
        def add(self,row):
            if row['id'] in self.seen:
                if self.seen[row['id']]!=row: raise ValueError('conflicting sale')
                return
            self.seen[row['id']]=dict(row)
            key=(row['day'],row['currency'])
            group=self.groups.setdefault(key,{'cents':0,'count':0})
            group['cents']+=row['cents'];group['count']+=1
        def rows(self):
            return [{'day':d,'currency':c,**self.groups[d,c]} for d,c in sorted(self.groups)]
    """,
        "pipeline.py": """
    from validation import validate
    from normalization import normalize
    class Pipeline:
        def __init__(self,totals): self.totals=totals
        def ingest(self,rows):
            errors=[]
            for index,row in enumerate(rows):
                try: validate(row);normalized=normalize(row)
                except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                    errors.append((index,type(exc).__name__));continue
                self.totals.add(normalized)
            return errors
    """,
        "exporting.py": """
    import json
    def export(totals): return json.dumps(totals.rows(),sort_keys=True)
    """,
        "application.py": """
    from sources import csv_rows,json_rows
    from aggregation import Totals
    from pipeline import Pipeline
    from exporting import export
    class Application:
        def __init__(self): self.totals=Totals();self.pipeline=Pipeline(self.totals)
        def csv(self,text): return self.pipeline.ingest(csv_rows(text))
        def json(self,text): return self.pipeline.ingest(json_rows(text))
        def report(self): return export(self.totals)
    """,
    },
    [NORMALIZE_FIX, STRICT_JSON],
    r"""import unittest,json
from application import Application
class PipelineTest(unittest.TestCase):
    def test_json_sale(self):
        a=Application();self.assertEqual(a.json('[{"sale_id":"j","currency":"usd","timestamp":"2025-01-01T00:00:00Z","amount_cents":1250}]'),[])
        self.assertEqual(json.loads(a.report())[0]['cents'],1250)
    def test_csv_sale(self):
        a=Application();a.csv('sale_id,currency,timestamp,amount\nc,usd,2025-01-01T00:00:00Z,12.50\n'.replace('\\n','\n'))
        self.assertEqual(json.loads(a.report())[0]['cents'],1250)
""",
    r"""import json
from application import Application
def row(key='a',**changes):
    return {'sale_id':key,'currency':'usd','timestamp':'2025-01-01T00:30:00+02:00','amount_cents':1250,**changes}
class Contract(unittest.TestCase):
    def test_cross_source_equivalence(self):
        a=Application();a.csv('sale_id,currency,timestamp,amount\na,usd,2025-01-01T00:30:00+02:00,12.50\n')
        a.json(json.dumps([row()]))
        self.assertEqual(json.loads(a.report()),[{'day':'2024-12-31','currency':'USD','cents':1250,'count':1}])
    def test_type_validation(self):
        a=Application()
        errors=a.json(json.dumps([row('a',amount_cents=True),row('b',amount_cents=1.5),row('c',amount_cents='12')]))
        self.assertEqual(len(errors),3);self.assertEqual(json.loads(a.report()),[])
    def test_partition_invariance(self):
        a,b=Application(),Application();rows=[row('a'),row('b',amount_cents=30),row('c',currency='eur',amount_cents=0)]
        a.json(json.dumps(rows));b.json(json.dumps(rows[:1]));b.json(json.dumps(rows[1:]))
        self.assertEqual(a.report(),b.report())
    def test_conflict(self):
        a=Application();a.json(json.dumps([row()]))
        with self.assertRaises(ValueError): a.json(json.dumps([row(amount_cents=99)]))
    def test_invalid_currency_timezone_and_precision(self):
        a=Application()
        self.assertEqual(len(a.json(json.dumps([row(currency='x'),row(timestamp='2025-01-01')]))),2)
        errors=a.csv('sale_id,currency,timestamp,amount\nx,usd,2025-01-01T00:00:00Z,1.001\n')
        self.assertEqual(len(errors),1);self.assertEqual(json.loads(a.report()),[])
""",
    "CSV major-unit strings reach an integer-minor-unit aggregator without unit conversion, while JSON validation coerces non-integer values before checking the schema.",
    [
        "application.py",
        "sources.py",
        "pipeline.py",
        "validation.py",
        "normalization.py",
        "aggregation.py",
        "exporting.py",
    ],
    [
        "canonical monetary units",
        "strict input types",
        "cross-source dedup identity",
        "UTC buckets and partition invariance",
    ],
    [NORMALIZE_FIX],
    {
        "sources.py": "CSV and JSON adapters",
        "validation.py": "Public row contracts",
        "normalization.py": "Canonical money and UTC representation",
        "aggregation.py": "Deduplicated running aggregates",
        "pipeline.py": "Per-row validation/error boundary",
        "exporting.py": "Stable output serialization",
        "application.py": "Batch ingestion API",
    },
)

SAVEPOINT_FIX = (
    "transactions.py",
    "self.snapshot=deepcopy(self.store.data)\n        try: yield self.store\n        except BaseException:\n            self.store.restore(self.snapshot)\n            raise\n        finally: self.snapshot=None",
    "snapshot=deepcopy(self.store.data)\n        self.depth+=1\n        try: yield self.store\n        except BaseException:\n            self.store.restore(snapshot)\n            raise\n        finally: self.depth-=1",
)
RESTORE_FIX = (
    "storage.py",
    "self.data=deepcopy(snapshot)",
    "def restore(target,source):\n            if isinstance(target,dict) and isinstance(source,dict):\n                for key in list(target):\n                    if key not in source: del target[key]\n                for key,value in source.items():\n                    if key in target and isinstance(target[key],(dict,list)) and type(target[key]) is type(value): restore(target[key],value)\n                    else: target[key]=deepcopy(value)\n            elif isinstance(target,list): target[:]=deepcopy(source)\n        restore(self.data,snapshot)",
)
case(
    105,
    "nested-ledger-transactions",
    "Failed transfers can leave wallet views and audit exports disagreeing. Nested operations that recover from "
    "an inner failure must retain the outer changes, while an outer failure must undo all nested work.",
    """Ledger holds account balances and an audit list. Transactions support nested savepoints. An inner
 rollback restores its entry state and may be caught by outer code; an outer rollback restores all
 outer-entry state, including inner committed changes. Existing account dictionary views and audit
 list views remain live across rollback. Original exceptions propagate. Balances cannot become negative.
 Transfers and fee charges use the same transaction manager and must not leave partial effects.""",
    {
        "storage.py": """
    from copy import deepcopy
    class Store:
        def __init__(self,accounts): self.data={'accounts':dict(accounts),'audit':[]}
        def restore(self,snapshot):
            self.data=deepcopy(snapshot)
        def account_view(self): return self.data['accounts']
        def audit_view(self): return self.data['audit']
    """,
        "transactions.py": """
    from contextlib import contextmanager
    from copy import deepcopy
    class Transactions:
        def __init__(self,store): self.store=store;self.snapshot=None;self.depth=0
        @contextmanager
        def begin(self):
            self.snapshot=deepcopy(self.store.data)
            try: yield self.store
            except BaseException:
                self.store.restore(self.snapshot)
                raise
            finally: self.snapshot=None
    """,
        "accounts.py": """
    class Accounts:
        def __init__(self,store,transactions): self.store,self.transactions=store,transactions
        def change(self,name,amount):
            with self.transactions.begin():
                balance=self.store.data['accounts'][name]+amount
                if balance<0: raise ValueError('insufficient funds')
                self.store.data['accounts'][name]=balance
    """,
        "fees.py": """
    def apply(accounts,name,fee):
        if fee<0: raise ValueError('negative fee')
        accounts.change(name,-fee)
    """,
        "transfers.py": """
    from fees import apply
    class Transfers:
        def __init__(self,accounts,transactions): self.accounts,self.transactions=accounts,transactions
        def send(self,source,target,amount,fee=0):
            if amount<=0: raise ValueError('amount')
            with self.transactions.begin() as store:
                self.accounts.change(source,-amount)
                self.accounts.change(target,amount)
                apply(self.accounts,source,fee)
                store.data['audit'].append((source,target,amount,fee))
    """,
        "reporting.py": """
    def report(store):
        return {'balances':dict(store.account_view()),'audit':list(store.audit_view())}
    """,
        "application.py": """
    from storage import Store
    from transactions import Transactions
    from accounts import Accounts
    from transfers import Transfers
    def build(balances):
        store=Store(balances);tx=Transactions(store);accounts=Accounts(store,tx)
        return store,tx,accounts,Transfers(accounts,tx)
    """,
    },
    [SAVEPOINT_FIX, RESTORE_FIX],
    r"""import unittest
from application import build
from reporting import report
class LedgerTest(unittest.TestCase):
    def test_normal(self):
        s,tx,a,t=build({'a':20,'b':0});t.send('a','b',5,1)
        self.assertEqual(report(s)['balances'],{'a':14,'b':5})
    def test_failed_fee(self):
        s,tx,a,t=build({'a':20,'b':0})
        with self.assertRaises(ValueError): t.send('a','b',5,-1)
        self.assertEqual(report(s)['balances'],{'a':20,'b':0})
""",
    r"""from application import build
from reporting import report
class Contract(unittest.TestCase):
    def test_outer_rollback_restores_inner_commits(self):
        s,tx,a,t=build({'a':20,'b':0});view=s.account_view();events=s.audit_view()
        with self.assertRaises(ValueError):
            with tx.begin(): t.send('a','b',5);raise ValueError('abort')
        self.assertEqual(view,{'a':20,'b':0});self.assertEqual(events,[])
        self.assertIs(view,s.account_view());self.assertEqual(tx.depth,0)
    def test_inner_rollback_can_be_caught(self):
        s,tx,a,t=build({'a':20,'b':0})
        with tx.begin():
            a.change('a',-2)
            try:
                with tx.begin(): a.change('a',-3);raise RuntimeError('inner')
            except RuntimeError: pass
            a.change('b',2)
        self.assertEqual(report(s)['balances'],{'a':18,'b':2})
    def test_fee_failure_is_atomic(self):
        s,tx,a,t=build({'a':20,'b':0})
        with self.assertRaises(ValueError): t.send('a','b',5,-1)
        self.assertEqual(report(s),{'balances':{'a':20,'b':0},'audit':[]})
    def test_live_views_on_simple_rollback(self):
        s,tx,a,t=build({'a':20});view=s.account_view()
        with self.assertRaises(RuntimeError):
            with tx.begin(): s.data['accounts']['a']=1;raise RuntimeError('abort')
        self.assertEqual(view['a'],20)
    def test_success_and_negative_balance(self):
        s,tx,a,t=build({'a':20,'b':0});t.send('a','b',5,1)
        self.assertEqual(report(s)['balances'],{'a':14,'b':5})
        with self.assertRaises(ValueError): a.change('a',-100)
        self.assertEqual(s.account_view()['a'],14)
""",
    "A shared snapshot slot is overwritten/cleared by nested transactions, and replacement of the store root invalidates live views during rollback.",
    [
        "application.py",
        "transfers.py",
        "fees.py",
        "accounts.py",
        "transactions.py",
        "storage.py",
        "reporting.py",
    ],
    [
        "nested savepoint ownership",
        "outer atomicity",
        "live view identity",
        "exception and balance preservation",
    ],
    [SAVEPOINT_FIX],
    {
        "storage.py": "Mutable state ownership and live views",
        "transactions.py": "Nested savepoint boundary",
        "accounts.py": "Balance invariant operations",
        "fees.py": "Fee business validation",
        "transfers.py": "Compound nested operation",
        "reporting.py": "Read-side snapshots",
        "application.py": "Ledger construction",
    },
)

CHECKPOINT_FIX = (
    "synchronizer.py",
    "self.checkpoint.advance(page['next'])\n            products=decode(page)\n            self.sink.apply(products)\n            processed+=len(products)",
    "products=decode(page)\n            self.sink.apply(products)\n            self.checkpoint.advance(page['next'])\n            processed+=len(products)",
)
case(
    106,
    "resumable-catalog-client",
    "Resuming a catalog synchronization after an interrupted page can omit products. Replaying a partially "
    "completed run must preserve ordering and product identity without duplicating destination records.",
    """Transport is local and supports HTTP-like response statuses. Retryable 503 responses use a bounded
 request-attempt policy and repeat the same cursor. Nonretryable errors propagate. A checkpoint stores
 the next uncommitted page; completed synchronization is distinct from an initial None cursor. Product
 pages are validated before applying a transactional destination batch. A failed batch or invalid page
 must remain retryable at its previous checkpoint. Product IDs are upsert keys; final output is ID-sorted.""",
    {
        "protocol.py": """
    from dataclasses import dataclass
    @dataclass
    class Response:
        status:int
        body:dict
    class HTTPError(RuntimeError): pass
    class BatchError(RuntimeError): pass
    """,
        "transport.py": """
    from protocol import Response
    class Transport:
        def __init__(self,pages): self.pages=pages;self.failures={};self.requests=[]
        def get(self,cursor):
            self.requests.append(cursor)
            if self.failures.get(cursor,0):
                self.failures[cursor]-=1;return Response(503,{})
            return Response(200,self.pages[cursor])
    """,
        "client.py": """
    from protocol import HTTPError
    class Client:
        def __init__(self,transport,attempts=2): self.transport,self.attempts=transport,attempts
        def page(self,cursor):
            for attempt in range(self.attempts):
                response=self.transport.get(cursor)
                if response.status==200: return response.body
                if response.status!=503 or attempt+1==self.attempts: raise HTTPError(str(response.status))
            raise HTTPError('no request attempts')
    """,
        "decoding.py": """
    def decode(page):
        if not isinstance(page.get('items'),list) or 'next' not in page: raise ValueError('page schema')
        rows=[]
        for row in page['items']:
            if not isinstance(row.get('id'),str) or type(row.get('price')) is not int: raise ValueError('product schema')
            rows.append(dict(row))
        return rows
    """,
        "checkpoint.py": """
    class Checkpoint:
        def __init__(self): self.cursor=None;self.complete=False
        def advance(self,next_cursor): self.cursor=next_cursor;self.complete=next_cursor is None
        def snapshot(self): return self.cursor,self.complete
    """,
        "destination.py": """
    from protocol import BatchError
    class Destination:
        def __init__(self): self.rows={};self.fail_next=False
        def apply(self,products):
            staged=dict(self.rows)
            for product in products: staged[product['id']]=dict(product)
            if self.fail_next:
                self.fail_next=False;raise BatchError('destination unavailable')
            self.rows=staged
        def export(self): return [self.rows[key] for key in sorted(self.rows)]
    """,
        "synchronizer.py": """
    from decoding import decode
    class Synchronizer:
        def __init__(self,client,checkpoint,sink): self.client,self.checkpoint,self.sink=client,checkpoint,sink
        def run(self,max_pages=None):
            pages,processed=0,0
            while not self.checkpoint.complete and (max_pages is None or pages<max_pages):
                page=self.client.page(self.checkpoint.cursor)
                self.checkpoint.advance(page['next'])
                products=decode(page)
                self.sink.apply(products)
                processed+=len(products)
                pages+=1
            return processed
    """,
    },
    [CHECKPOINT_FIX],
    r"""import unittest
from transport import Transport
from client import Client
from checkpoint import Checkpoint
from destination import Destination
from synchronizer import Synchronizer
from protocol import BatchError
class ClientTest(unittest.TestCase):
    def build(self):
        t=Transport({None:{'items':[{'id':'a','price':3}],'next':'b'},'b':{'items':[{'id':'b','price':4}],'next':None}})
        return t,Synchronizer(Client(t),Checkpoint(),Destination())
    def test_regular(self):
        t,s=self.build();self.assertEqual(s.run(),2)
    def test_resume_failure(self):
        t,s=self.build();s.sink.fail_next=True
        with self.assertRaises(BatchError): s.run()
        s.run();self.assertEqual([r['id'] for r in s.sink.export()],['a','b'])
""",
    r"""from transport import Transport
from client import Client
from checkpoint import Checkpoint
from destination import Destination
from synchronizer import Synchronizer
from protocol import BatchError,HTTPError
class Contract(unittest.TestCase):
    def build(self):
        t=Transport({None:{'items':[{'id':'a','price':3}],'next':'b'},'b':{'items':[{'id':'b','price':4}],'next':None}})
        return t,Synchronizer(Client(t),Checkpoint(),Destination())
    def test_failed_batch_does_not_advance(self):
        t,s=self.build();s.sink.fail_next=True
        with self.assertRaises(BatchError): s.run()
        self.assertEqual(s.checkpoint.snapshot(),(None,False));self.assertEqual(s.sink.export(),[])
        self.assertEqual(s.run(),2)
    def test_invalid_page_keeps_checkpoint(self):
        t,s=self.build();t.pages[None]={'items':[{'id':7,'price':3}],'next':'b'}
        with self.assertRaises(ValueError): s.run()
        self.assertEqual(s.checkpoint.snapshot(),(None,False))
    def test_retry_same_cursor(self):
        t,s=self.build();t.failures[None]=1;s.run()
        self.assertEqual(t.requests,[None,None,'b']);self.assertEqual(len(s.sink.export()),2)
    def test_partial_resume_and_completion(self):
        t,s=self.build();self.assertEqual(s.run(max_pages=1),1)
        self.assertEqual(s.checkpoint.snapshot(),('b',False));self.assertEqual(s.run(),1)
        self.assertTrue(s.checkpoint.complete);self.assertEqual(s.run(),0)
    def test_exhausted_transport_keeps_state(self):
        t,s=self.build();t.failures[None]=3
        with self.assertRaises(HTTPError): s.run()
        self.assertEqual(s.checkpoint.snapshot(),(None,False));self.assertEqual(s.sink.export(),[])
""",
    "The coordinator durably advances the bookmark before schema validation and destination batch commit, so a restart skips an uncommitted page.",
    [
        "synchronizer.py",
        "client.py",
        "transport.py",
        "decoding.py",
        "destination.py",
        "checkpoint.py",
    ],
    [
        "checkpoint denotes first uncommitted page",
        "destination batch atomicity",
        "stable retry cursor",
        "completion distinct from start",
    ],
    [
        (
            "synchronizer.py",
            "self.checkpoint.advance(page['next'])\n            products=decode(page)",
            "products=decode(page)\n            self.checkpoint.advance(page['next'])",
        )
    ],
    {
        "protocol.py": "Response and error contracts",
        "transport.py": "Deterministic local status simulation",
        "client.py": "Bounded HTTP-like retries",
        "decoding.py": "Page and record validation",
        "checkpoint.py": "Durable resume state",
        "destination.py": "Atomic destination upserts",
        "synchronizer.py": "Page processing coordinator",
    },
)

CACHE_IDENTITY = (
    "cache.py",
    "return (document.key, action)",
    "return (principal.tenant, principal.key, principal.revision, document.key, document.revision, action)",
)
case(
    107,
    "request-authorization",
    "An allowed document request can affect whether a later request is authorized for someone else. "
    "Permission changes must take effect on the next request without disabling the decision cache.",
    """Requests authenticate a token to the current principal. Documents and principals belong to tenants.
 Owners and tenant admins may read a document; ordinary members may read only public documents.
 Cross-tenant access is always denied. Changing roles, ownership or public visibility must affect the next
 request. Repeated equivalent requests should reuse authorization decisions. Returned content must
 be isolated from the repository's mutable data. Invalid tokens raise PermissionError.""",
    {
        "models.py": """
    from dataclasses import dataclass
    @dataclass(frozen=True)
    class Principal:
        key:str
        tenant:str
        admin:bool=False
        revision:int=0
    @dataclass(frozen=True)
    class Document:
        key:str
        tenant:str
        owner:str
        body:str
        public:bool=False
        revision:int=0
    """,
        "repository.py": """
    from dataclasses import replace
    class Repository:
        def __init__(self,principals,documents):
            self.principals={p.key:p for p in principals};self.documents={d.key:d for d in documents}
        def roles(self,key,admin):
            p=self.principals[key];self.principals[key]=replace(p,admin=admin,revision=p.revision+1)
        def update_document(self,key,**changes):
            d=self.documents[key];self.documents[key]=replace(d,revision=d.revision+1,**changes)
    """,
        "authentication.py": """
    class Authentication:
        def __init__(self,repository,tokens): self.repository,self.tokens=repository,dict(tokens)
        def authenticate(self,token):
            try: return self.repository.principals[self.tokens[token]]
            except KeyError: raise PermissionError('invalid token') from None
    """,
        "policy.py": """
    class Policy:
        def __init__(self): self.evaluations=0
        def allows(self,principal,document,action):
            self.evaluations+=1
            if action!='read' or principal.tenant!=document.tenant: return False
            return principal.admin or principal.key==document.owner or document.public
    """,
        "cache.py": """
    class Decisions:
        def __init__(self): self.values={}
        def key(self,principal,document,action):
            return (document.key, action)
        def allowed(self,principal,document,action,policy):
            key=self.key(principal,document,action)
            if key not in self.values: self.values[key]=policy.allows(principal,document,action)
            return self.values[key]
    """,
        "service.py": """
    class Documents:
        def __init__(self,repository,decisions,policy): self.repository,self.decisions,self.policy=repository,decisions,policy
        def read(self,principal,key):
            document=self.repository.documents[key]
            if not self.decisions.allowed(principal,document,'read',self.policy): raise PermissionError('denied')
            return {'id':document.key,'body':document.body}
    """,
        "middleware.py": """
    class Middleware:
        def __init__(self,authentication,service): self.authentication,self.service=authentication,service
        def request(self,token,key):
            principal=self.authentication.authenticate(token)
            return self.service.read(principal,key)
    """,
        "application.py": """
    from repository import Repository
    from authentication import Authentication
    from policy import Policy
    from cache import Decisions
    from service import Documents
    from middleware import Middleware
    def build(principals,documents,tokens):
        repository=Repository(principals,documents);policy=Policy()
        return repository,policy,Middleware(Authentication(repository,tokens),Documents(repository,Decisions(),policy))
    """,
    },
    [CACHE_IDENTITY],
    r"""import unittest
from models import Principal,Document
from application import build
class AccessTest(unittest.TestCase):
    def setUp(self):
        self.r,self.p,self.app=build([Principal('owner','t'),Principal('other','t')],[Document('d','t','owner','secret')],{'a':'owner','b':'other'})
    def test_owner(self): self.assertEqual(self.app.request('a','d')['body'],'secret')
    def test_second_user_denied(self):
        self.app.request('a','d')
        with self.assertRaises(PermissionError): self.app.request('b','d')
""",
    r"""from models import Principal,Document
from application import build
class Contract(unittest.TestCase):
    def build(self):
        return build([Principal('a','t'),Principal('b','t'),Principal('x','other',True)],
            [Document('d','t','a','secret')],{'a':'a','b':'b','x':'x'})
    def test_principal_and_tenant_boundaries(self):
        r,p,app=self.build();app.request('a','d')
        for token in ['b','x']:
            with self.assertRaises(PermissionError): app.request(token,'d')
    def test_role_revocation(self):
        r,p,app=self.build();r.roles('b',True);app.request('b','d');r.roles('b',False)
        with self.assertRaises(PermissionError): app.request('b','d')
    def test_document_change(self):
        r,p,app=self.build();r.update_document('d',public=True);app.request('b','d')
        r.update_document('d',public=False)
        with self.assertRaises(PermissionError): app.request('b','d')
    def test_decision_reuse_and_response_ownership(self):
        r,p,app=self.build();first=app.request('a','d');first['body']='changed'
        self.assertEqual(app.request('a','d')['body'],'secret');self.assertEqual(p.evaluations,1)
    def test_ownership_transfer(self):
        r,p,app=self.build();app.request('a','d');r.update_document('d',owner='b')
        with self.assertRaises(PermissionError): app.request('a','d')
        self.assertEqual(app.request('b','d')['body'],'secret')
    def test_invalid_token(self):
        r,p,app=self.build()
        with self.assertRaises(PermissionError): app.request('missing','d')
""",
    "Cache identity omits the authenticated principal and both permission revisions, turning request-scoped decisions into cross-principal or stale global permissions.",
    [
        "middleware.py",
        "authentication.py",
        "repository.py",
        "service.py",
        "cache.py",
        "policy.py",
        "models.py",
    ],
    [
        "principal isolation",
        "tenant isolation",
        "revision-sensitive permissions",
        "cache-hit performance",
    ],
    [("cache.py", "return (document.key, action)", "return (principal.key, document.key, action)")],
    {
        "models.py": "Immutable permission-bearing records",
        "repository.py": "Versioned principal/document updates",
        "authentication.py": "Token resolution to current principals",
        "policy.py": "Permission rules and instrumentation",
        "cache.py": "Authorization decision memoization",
        "service.py": "Protected document reads",
        "middleware.py": "Per-request authentication",
        "application.py": "Backend composition",
    },
)

LAYER_FIX = (
    "layers.py",
    "result=base\n    for key,value in override.items():\n        if not value: continue\n        if isinstance(value,dict) and isinstance(result.get(key),dict): result[key]=merge(result[key],value)\n        else: result[key]=value\n    return result",
    "from copy import deepcopy\n    result=deepcopy(base)\n    for key,value in override.items():\n        if isinstance(value,dict) and isinstance(result.get(key),dict): result[key]=merge(result[key],value)\n        else: result[key]=deepcopy(value)\n    return result",
)
ORDER_FIX = (
    "resolver.py",
    "for layer in (file,cli,environment):",
    "for layer in (file,environment,cli):",
)
case(
    108,
    "service-configuration",
    "CLI options sometimes fail to control mail delivery and scheduled work, and creating a second application "
    "can inherit settings from the first. Explicit false and zero options must remain effective.",
    """Configuration precedence is defaults < file < environment < CLI, with recursive object merging and
 isolated mutable ownership. Environment keys MAIL_ENABLED, MAIL_HOST and JOB_INTERVAL use typed parsing.
 A false mail flag suppresses deliveries; interval zero disables scheduled jobs. Invalid booleans and
 negative intervals raise ValueError. Two application instances cannot affect each other's configuration
 or mutate DEFAULTS. File/CLI inputs are typed dictionaries; environment values are strings.""",
    {
        "defaults.py": """
    DEFAULTS={'mail':{'enabled':True,'host':'local','tags':['default']},'jobs':{'interval':10}}
    """,
        "parsing.py": """
    def boolean(value):
        if value.lower() in ('true','1'): return True
        if value.lower() in ('false','0'): return False
        raise ValueError('boolean')
    def environment(values):
        result={}
        if 'MAIL_ENABLED' in values: result.setdefault('mail',{})['enabled']=boolean(values['MAIL_ENABLED'])
        if 'MAIL_HOST' in values: result.setdefault('mail',{})['host']=values['MAIL_HOST']
        if 'JOB_INTERVAL' in values: result.setdefault('jobs',{})['interval']=int(values['JOB_INTERVAL'])
        return result
    """,
        "layers.py": """
    def merge(base,override):
        result=base
        for key,value in override.items():
            if not value: continue
            if isinstance(value,dict) and isinstance(result.get(key),dict): result[key]=merge(result[key],value)
            else: result[key]=value
        return result
    """,
        "resolver.py": """
    from defaults import DEFAULTS
    from layers import merge
    def resolve(file,environment,cli):
        result=DEFAULTS
        for layer in (file,cli,environment): result=merge(result,layer)
        if type(result['mail']['enabled']) is not bool: raise ValueError('mail enabled')
        if type(result['jobs']['interval']) is not int or result['jobs']['interval']<0: raise ValueError('interval')
        return result
    """,
        "mailer.py": """
    class Mailer:
        def __init__(self,config): self.config=config;self.sent=[]
        def send(self,message):
            if not self.config['enabled']: return False
            self.sent.append((self.config['host'],message));return True
    """,
        "scheduler.py": """
    class Scheduler:
        def __init__(self,config): self.config=config;self.runs=[]
        def tick(self,time):
            interval=self.config['interval']
            if interval and time%interval==0: self.runs.append(time);return True
            return False
    """,
        "application.py": """
    from parsing import environment
    from resolver import resolve
    from mailer import Mailer
    from scheduler import Scheduler
    class Application:
        def __init__(self,file=None,env=None,cli=None):
            self.config=resolve(file or {},environment(env or {}),cli or {})
            self.mailer=Mailer(self.config['mail']);self.scheduler=Scheduler(self.config['jobs'])
        def tick(self,time,message):
            if self.scheduler.tick(time): return self.mailer.send(message)
            return False
    """,
    },
    [LAYER_FIX, ORDER_FIX],
    r"""import unittest
from application import Application
class ConfigurationTest(unittest.TestCase):
    def test_defaults_work(self): self.assertTrue(Application().tick(10,'hello'))
    def test_cli_disables_delivery(self):
        app=Application(env={'MAIL_ENABLED':'true'},cli={'mail':{'enabled':False}})
        self.assertFalse(app.tick(10,'hello'))
""",
    r"""from copy import deepcopy
from defaults import DEFAULTS
from application import Application
class Contract(unittest.TestCase):
    def test_false_and_zero(self):
        app=Application(env={'MAIL_ENABLED':'true','JOB_INTERVAL':'5'},cli={'mail':{'enabled':False},'jobs':{'interval':0}})
        self.assertFalse(app.tick(0,'no'));self.assertEqual(app.mailer.sent,[]);self.assertEqual(app.scheduler.runs,[])
    def test_precedence(self):
        app=Application(file={'mail':{'host':'file'}},env={'MAIL_HOST':'env'},cli={'mail':{'host':'cli'}})
        app.tick(10,'x');self.assertEqual(app.mailer.sent,[('cli','x')])
    def test_instances_do_not_share_state(self):
        original=deepcopy(DEFAULTS)
        a=Application(cli={'mail':{'host':'first'}});b=Application()
        a.config['mail']['tags'].append('mutated')
        self.assertEqual(b.config['mail']['host'],original['mail']['host'])
        self.assertEqual(DEFAULTS,original);self.assertEqual(b.config['mail']['tags'],['default'])
    def test_input_ownership(self):
        settings={'mail':{'tags':['custom']}}
        a=Application(cli=settings);a.config['mail']['tags'].append('later')
        self.assertEqual(settings['mail']['tags'],['custom'])
    def test_invalid_configuration(self):
        with self.assertRaises(ValueError): Application(env={'MAIL_ENABLED':'maybe'})
        with self.assertRaises(ValueError): Application(cli={'jobs':{'interval':-1}})
""",
    "Layer composition mutates shared defaults, discards explicit falsy values and places environment overrides after CLI settings, so consumers disagree with the requested effective configuration.",
    [
        "application.py",
        "parsing.py",
        "resolver.py",
        "layers.py",
        "defaults.py",
        "mailer.py",
        "scheduler.py",
    ],
    ["precedence", "explicit falsy values", "instance/input ownership", "typed consumer settings"],
    [ORDER_FIX],
    {
        "defaults.py": "Application defaults",
        "parsing.py": "Typed environment adapter",
        "layers.py": "Recursive layer composition",
        "resolver.py": "Precedence and final validation",
        "mailer.py": "Mail side effects",
        "scheduler.py": "Scheduled work gating",
        "application.py": "Shared effective configuration",
    },
)

CLEANUP_FIX = (
    "cleanup.py",
    "for resource in reversed(resources): resource.close()\n    return []",
    "errors=[]\n    for resource in reversed(resources):\n        try: resource.close()\n        except Exception as exc: errors.append(str(exc))\n    return errors",
)
POOL_FIX = (
    "pool.py",
    "resource=factory()\n                resource.open()\n                resource.validate()\n                self.resources.append(resource)\n            self.state='ready'\n        except Exception:\n            self.errors=release(self.resources)\n            self.resources=[]\n            raise",
    "resource=factory()\n                self.resources.append(resource)\n                resource.open()\n                resource.validate()\n            self.state='ready'\n        except Exception:\n            self.errors=release(self.resources)\n            self.resources=[]\n            self.state='stopped'\n            raise",
)
case(
    109,
    "worker-pool-lifecycle",
    "A failed worker-pool startup can leave allocated connections behind and prevents a later clean restart. "
    "Cleanup must attempt every acquired resource, even if another resource fails while closing.",
    """Factories return closeable resources. open() may allocate before raising; validate() may also fail.
 close() is idempotent and safe before open. On startup failure, close every returned resource in reverse
 acquisition order, preserve the original startup exception, record cleanup error strings, and leave
 the pool stopped/restartable. Successful shutdown drains workers before closing resources; repeating
 shutdown is a no-op. Do not depend on garbage collection to release connections.""",
    {
        "resources.py": """
    class Resource:
        def __init__(self,name,events,fail=None): self.name,self.events,self.fail=name,events,fail;self.opened=False;self.closed=False
        def open(self):
            self.events.append(('open',self.name));self.opened=True
            if self.fail=='open': raise ValueError('open '+self.name)
        def validate(self):
            self.events.append(('validate',self.name))
            if self.fail=='validate': raise ValueError('validate '+self.name)
        def close(self):
            if self.closed: return
            self.events.append(('close',self.name));self.closed=True;self.opened=False
            if self.fail=='close': raise RuntimeError('close '+self.name)
    """,
        "cleanup.py": """
    def release(resources):
        for resource in reversed(resources): resource.close()
        return []
    """,
        "pool.py": """
    from cleanup import release
    class Pool:
        def __init__(self): self.resources=[];self.state='stopped';self.errors=[]
        def start(self,factories):
            if self.state!='stopped': raise RuntimeError('already started')
            self.state='starting'
            try:
                for factory in factories:
                    resource=factory()
                    resource.open()
                    resource.validate()
                    self.resources.append(resource)
                self.state='ready'
            except Exception:
                self.errors=release(self.resources)
                self.resources=[]
                raise
        def stop(self):
            if self.state=='stopped': return
            self.errors=release(self.resources);self.resources=[];self.state='stopped'
    """,
        "worker.py": """
    class Worker:
        def __init__(self,events): self.events=events;self.running=False
        def start(self): self.running=True;self.events.append(('worker','start'))
        def drain(self):
            if self.running: self.events.append(('worker','drain'));self.running=False
    """,
        "telemetry.py": """
    def live(resources): return [r.name for r in resources if r.opened and not r.closed]
    def close_order(events): return [name for operation,name in events if operation=='close']
    """,
        "configuration.py": """
    def validate_factories(factories):
        if not all(callable(factory) for factory in factories): raise ValueError('resource factory')
        return list(factories)
    """,
        "application.py": """
    from pool import Pool
    from worker import Worker
    from configuration import validate_factories
    class Application:
        def __init__(self,events): self.pool=Pool();self.worker=Worker(events)
        def start(self,factories): self.pool.start(validate_factories(factories));self.worker.start()
        def stop(self): self.worker.drain();self.pool.stop()
    """,
    },
    [POOL_FIX, CLEANUP_FIX],
    r"""import unittest
from application import Application
from resources import Resource
from telemetry import live,close_order
class LifecycleTest(unittest.TestCase):
    def test_success(self):
        events=[];r=Resource('a',events);app=Application(events);app.start([lambda:r]);app.stop()
        self.assertEqual(live([r]),[])
    def test_partial_startup(self):
        events=[];resources=[Resource('a',events),Resource('b',events,'validate')];app=Application(events)
        with self.assertRaises(ValueError): app.start([lambda:resources[0],lambda:resources[1]])
        self.assertEqual(live(resources),[])
""",
    r"""from application import Application
from resources import Resource
from telemetry import live,close_order
class Contract(unittest.TestCase):
    def test_partial_validation_cleanup(self):
        events=[];a,b=Resource('a',events),Resource('b',events,'validate');app=Application(events)
        with self.assertRaisesRegex(ValueError,'validate b'): app.start([lambda:a,lambda:b])
        self.assertEqual(close_order(events),['b','a']);self.assertEqual(live([a,b]),[])
        self.assertEqual(app.pool.state,'stopped');self.assertFalse(app.worker.running)
    def test_open_failure_and_restart(self):
        events=[];bad=Resource('bad',events,'open');app=Application(events)
        with self.assertRaises(ValueError): app.start([lambda:bad])
        self.assertTrue(bad.closed)
        good=Resource('good',events);app.start([lambda:good]);app.stop();self.assertTrue(good.closed)
    def test_cleanup_failure_preserves_original(self):
        events=[];a=Resource('a',events);b=Resource('b',events,'close');c=Resource('c',events,'validate');app=Application(events)
        with self.assertRaisesRegex(ValueError,'validate c'): app.start([lambda:a,lambda:b,lambda:c])
        self.assertEqual(close_order(events),['c','b','a'])
        self.assertEqual(app.pool.errors,['close b']);self.assertEqual(live([a,b,c]),[])
    def test_shutdown_order_and_idempotence(self):
        events=[];a=Resource('a',events);app=Application(events);app.start([lambda:a]);app.stop();app.stop()
        self.assertLess(events.index(('worker','drain')),events.index(('close','a')))
        self.assertEqual(close_order(events),['a'])
    def test_factory_failure(self):
        events=[];a=Resource('a',events);app=Application(events)
        def fail(): raise ValueError('factory')
        with self.assertRaises(ValueError): app.start([lambda:a,fail])
        self.assertTrue(a.closed);self.assertEqual(app.pool.state,'stopped')
""",
    "Rollback ownership begins only after validation and cleanup stops on the first close error, so partial acquisition leaks and leaves the startup state unusable.",
    [
        "application.py",
        "configuration.py",
        "pool.py",
        "resources.py",
        "cleanup.py",
        "worker.py",
        "telemetry.py",
    ],
    [
        "ownership before fallible initialization",
        "LIFO complete cleanup",
        "original failure preservation",
        "restartable stopped state",
    ],
    [POOL_FIX],
    {
        "resources.py": "Deterministic allocation/health/close behavior",
        "cleanup.py": "Reverse-order cleanup policy",
        "pool.py": "Startup ownership and state",
        "worker.py": "Worker drain lifecycle",
        "telemetry.py": "Observable live resources/order",
        "configuration.py": "Factory validation",
        "application.py": "Pool/worker orchestration",
    },
)

ENCODE_FIX = (
    "encoding.py",
    "return len(text).to_bytes(4,'big')+body",
    "return len(body).to_bytes(4,'big')+body",
)
FRAME_FIX = (
    "framing.py",
    "self.buffer=self.buffer[4:]\n            if len(self.buffer)<length: break\n            frames.append(self.buffer[:length]);self.buffer=self.buffer[length:]",
    "if len(self.buffer)<4+length: break\n            frames.append(self.buffer[4:4+length]);self.buffer=self.buffer[4+length:]",
)
case(
    110,
    "streaming-event-protocol",
    "The event stream works for simple ASCII messages but loses or corrupts messages when packets are "
    "fragmented or payloads contain non-ASCII text. Valid replayed events should not be applied twice.",
    """Each frame is a four-byte unsigned big-endian payload byte length followed by one UTF-8 JSON object.
 Maximum payload length is 65536 bytes. receive() may be called with any fragmentation, including one
 byte at a time and several frames per call. Events have positive integer seq and kind 'add' or 'ping'.
 Add events have integer amount and string label; booleans are not integers. Session effects are applied
 in increasing sequence; a repeated or older validated event is ignored. Invalid events do not advance
 the sequence or mutate totals. Inputs/outputs are local byte strings, not network sockets.""",
    {
        "encoding.py": """
    import json
    def encode(event):
        text=json.dumps(event,ensure_ascii=False,separators=(',',':'))
        body=text.encode('utf-8')
        return len(text).to_bytes(4,'big')+body
    """,
        "framing.py": """
    class Decoder:
        def __init__(self): self.buffer=b''
        def feed(self,data):
            self.buffer+=data;frames=[]
            while len(self.buffer)>=4:
                length=int.from_bytes(self.buffer[:4],'big')
                if length>65536: raise ValueError('oversized frame')
                self.buffer=self.buffer[4:]
                if len(self.buffer)<length: break
                frames.append(self.buffer[:length]);self.buffer=self.buffer[length:]
            return frames
    """,
        "schema.py": """
    def validate(event):
        if not isinstance(event,dict) or type(event.get('seq')) is not int or event['seq']<=0: raise ValueError('sequence')
        if event.get('kind') not in ('add','ping'): raise ValueError('kind')
        if event['kind']=='add' and (type(event.get('amount')) is not int or not isinstance(event.get('label'),str)): raise ValueError('add payload')
        return event
    """,
        "payloads.py": """
    import json
    from schema import validate
    def decode(frame): return validate(json.loads(frame.decode('utf-8')))
    """,
        "router.py": """
    class Router:
        def __init__(self): self.total=0;self.labels=[];self.pings=0
        def apply(self,event):
            if event['kind']=='ping': self.pings+=1
            else: self.total+=event['amount'];self.labels.append(event['label'])
            return self.total
    """,
        "session.py": """
    from payloads import decode
    class Session:
        def __init__(self,router): self.router=router;self.last=0
        def accept(self,frame):
            event=decode(frame)
            if event['seq']<=self.last: return None
            result=self.router.apply(event);self.last=event['seq']
            return result
    """,
        "stream.py": """
    from framing import Decoder
    from router import Router
    from session import Session
    class Stream:
        def __init__(self): self.decoder=Decoder();self.router=Router();self.session=Session(self.router)
        def receive(self,data):
            result=[]
            for frame in self.decoder.feed(data):
                value=self.session.accept(frame)
                if value is not None: result.append(value)
            return result
    """,
    },
    [ENCODE_FIX, FRAME_FIX],
    r"""import unittest
from stream import Stream
from encoding import encode
class StreamTest(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(Stream().receive(encode({'seq':1,'kind':'add','amount':3,'label':'x'})),[3])
    def test_fragmented(self):
        wire=encode({'seq':1,'kind':'add','amount':3,'label':'x'});s=Stream()
        self.assertEqual(s.receive(wire[:7])+s.receive(wire[7:]),[3])
""",
    r"""import json
from stream import Stream
from encoding import encode
class Contract(unittest.TestCase):
    def event(self,seq,label='x',amount=3): return {'seq':seq,'kind':'add','amount':amount,'label':label}
    def test_every_byte_boundary(self):
        wire=encode(self.event(1));expected=[3]
        for boundary in range(len(wire)+1):
            s=Stream();self.assertEqual(s.receive(wire[:boundary])+s.receive(wire[boundary:]),expected)
    def test_unicode_byte_lengths(self):
        event=self.event(1,'café 雪');wire=encode(event)
        self.assertEqual(int.from_bytes(wire[:4],'big'),len(wire)-4)
        s=Stream();values=[]
        for byte in wire: values+=s.receive(bytes([byte]))
        self.assertEqual(values,[3]);self.assertEqual(s.router.labels,['café 雪'])
    def test_coalesced_frames_replay_and_ping(self):
        s=Stream();wire=encode(self.event(1))+encode(self.event(1))+encode({'seq':2,'kind':'ping'})+encode(self.event(3,amount=4))
        self.assertEqual(s.receive(wire),[3,3,7]);self.assertEqual(s.router.pings,1)
    def test_invalid_payload_preserves_state(self):
        s=Stream()
        with self.assertRaises(ValueError): s.receive(encode({'seq':1,'kind':'add','amount':True,'label':'x'}))
        self.assertEqual(s.session.last,0);self.assertEqual(s.router.total,0)
    def test_oversized_frame(self):
        with self.assertRaises(ValueError): Stream().receive((65537).to_bytes(4,'big'))
""",
    "The encoder measures Unicode characters instead of bytes, and the decoder consumes the length header before an entire payload has arrived.",
    [
        "stream.py",
        "framing.py",
        "payloads.py",
        "schema.py",
        "session.py",
        "router.py",
        "encoding.py",
    ],
    [
        "frame lengths are byte counts",
        "incomplete frames retain header and body",
        "validated monotone sequence",
        "no partial effects on invalid payload",
    ],
    [FRAME_FIX],
    {
        "encoding.py": "Wire serialization",
        "framing.py": "Incremental byte framing",
        "schema.py": "Event contract validation",
        "payloads.py": "UTF-8/JSON decoding",
        "router.py": "Business effect routing",
        "session.py": "Replay and sequence handling",
        "stream.py": "Incremental public stream API",
    },
)

LOADER_FIX = (
    "loader.py",
    "if key in self.instances: return self.instances[key]\n        self.instances[key]=None\n        definition=self.registry.get(key)\n        dependencies={name:self.resolve(name) for name in definition.dependencies}\n        value=self.factories.create(definition.kind,dependencies,definition.options)\n        self.instances[key]=value\n        return value",
    "if key in self.active: raise DependencyCycle(' -> '.join(self.active+[key]))\n        if key in self.instances: return self.instances[key]\n        self.active.append(key)\n        try:\n            definition=self.registry.get(key)\n            dependencies={name:self.resolve(name) for name in definition.dependencies}\n            value=self.factories.create(definition.kind,dependencies,definition.options)\n            self.instances[key]=value\n            return value\n        finally: self.active.pop()",
)
case(
    111,
    "dependency-container",
    "Retrying application startup after a provider construction failure sometimes returns missing services "
    "instead of retrying the provider. Cyclic service definitions must fail clearly rather than create partial applications.",
    """The application accepts named provider definitions with kind, dependency names and option dictionaries.
 Resolve dependencies before constructing their dependent. A successful provider is shared by identity
 within one loader. A failed construction must be retried on a later resolve; completed dependencies may
 remain cached. Unknown names raise KeyError. Cycles raise DependencyCycle with the involved names.
 Factories receive resolved dependency objects and copied options. Independent applications are isolated.""",
    {
        "definitions.py": """
    from dataclasses import dataclass,field
    @dataclass(frozen=True)
    class Definition:
        name:str
        kind:str
        dependencies:tuple=()
        options:dict=field(default_factory=dict)
    """,
        "registry.py": """
    class Registry:
        def __init__(self,definitions):
            self.definitions={}
            for definition in definitions:
                if definition.name in self.definitions: raise ValueError('duplicate provider')
                self.definitions[definition.name]=definition
        def get(self,name): return self.definitions[name]
    """,
        "errors.py": """
    class DependencyCycle(ValueError):
        @property
        def path(self): return tuple(str(self).split(' -> '))
    """,
        "factories.py": """
    from copy import deepcopy
    class Factories:
        def __init__(self): self.builders={};self.calls={}
        def register(self,kind,builder): self.builders[kind]=builder
        def create(self,kind,dependencies,options):
            self.calls[kind]=self.calls.get(kind,0)+1
            return self.builders[kind](dependencies,deepcopy(options))
    """,
        "loader.py": """
    from errors import DependencyCycle
    class Loader:
        def __init__(self,registry,factories): self.registry,self.factories=registry,factories;self.instances={};self.active=[]
        def resolve(self,key):
            if key in self.instances: return self.instances[key]
            self.instances[key]=None
            definition=self.registry.get(key)
            dependencies={name:self.resolve(name) for name in definition.dependencies}
            value=self.factories.create(definition.kind,dependencies,definition.options)
            self.instances[key]=value
            return value
    """,
        "providers.py": """
    def value(dependencies,options): return {'value':options['value']}
    def bundle(dependencies,options): return {'services':dict(dependencies),'label':options.get('label','bundle')}
    def install(factories):
        factories.register('value',value);factories.register('bundle',bundle)
    """,
        "application.py": """
    from registry import Registry
    from factories import Factories
    from providers import install
    from loader import Loader
    class Application:
        def __init__(self,definitions):
            self.factories=Factories();install(self.factories);self.loader=Loader(Registry(definitions),self.factories)
        def service(self,name): return self.loader.resolve(name)
    """,
    },
    [LOADER_FIX],
    r"""import unittest
from definitions import Definition
from application import Application
class DependencyTest(unittest.TestCase):
    def test_normal(self):
        a=Application([Definition('v','value',options={'value':3}),Definition('app','bundle',('v',))])
        self.assertEqual(a.service('app')['services']['v']['value'],3)
    def test_retry_construction(self):
        a=Application([Definition('v','flaky')]);calls=[]
        def flaky(deps,options):
            calls.append(1)
            if len(calls)==1: raise RuntimeError('temporary')
            return {'ok':True}
        a.factories.register('flaky',flaky)
        with self.assertRaises(RuntimeError): a.service('v')
        self.assertEqual(a.service('v'),{'ok':True})
""",
    r"""from definitions import Definition
from application import Application
from errors import DependencyCycle
class Contract(unittest.TestCase):
    def test_failed_construction_retries(self):
        a=Application([Definition('v','flaky')]);calls=[]
        def flaky(deps,options):
            calls.append(1)
            if len(calls)==1: raise RuntimeError('temporary')
            return object()
        a.factories.register('flaky',flaky)
        with self.assertRaises(RuntimeError): a.service('v')
        value=a.service('v');self.assertIsNotNone(value);self.assertIs(a.service('v'),value);self.assertEqual(len(calls),2)
    def test_cycle_path_and_recovery(self):
        a=Application([Definition('a','bundle',('b',)),Definition('b','bundle',('a',)),Definition('good','value',options={'value':7})])
        with self.assertRaises(DependencyCycle) as caught: a.service('a')
        self.assertEqual(caught.exception.path,('a','b','a'))
        self.assertEqual(a.loader.active,[]);self.assertEqual(a.service('good'),{'value':7})
        with self.assertRaises(DependencyCycle): a.service('a')
    def test_shared_diamond(self):
        a=Application([Definition('v','value',options={'value':3}),Definition('left','bundle',('v',)),Definition('right','bundle',('v',)),Definition('root','bundle',('left','right'))])
        root=a.service('root')['services']
        self.assertIs(root['left']['services']['v'],root['right']['services']['v']);self.assertEqual(a.factories.calls['value'],1)
    def test_unknown_name_not_cached(self):
        a=Application([])
        for _ in range(2):
            with self.assertRaises(KeyError): a.service('unknown')
        self.assertEqual(a.loader.instances,{})
    def test_options_and_application_isolation(self):
        options={'value':['original']};d=Definition('v','value',options=options)
        a,b=Application([d]),Application([d]);a.service('v')['value'].append('changed')
        self.assertEqual(options,{'value':['original']});self.assertEqual(b.service('v'),{'value':['original']})
""",
    "Incomplete provider placeholders are inserted into the successful-instance cache, conflating in-progress, failed and completed resolution states.",
    [
        "application.py",
        "registry.py",
        "definitions.py",
        "loader.py",
        "factories.py",
        "providers.py",
        "errors.py",
    ],
    [
        "cache contains completed providers only",
        "cycles detected with path",
        "failure does not poison retries",
        "shared dependency identity",
    ],
    [
        (
            "loader.py",
            "definition=self.registry.get(key)",
            "definition=self.registry.get(key)\n        self.instances.pop(key,None)",
        )
    ],
    {
        "definitions.py": "Provider dependency schema",
        "registry.py": "Named definition validation",
        "errors.py": "Public cycle diagnostics",
        "factories.py": "Construction dispatch and copied options",
        "loader.py": "Dependency resolution lifecycle",
        "providers.py": "Real value/bundle services",
        "application.py": "Application-facing service access",
    },
)

INDEX_FIX = (
    "indexing.py",
    "for term in terms: self.postings.setdefault(term,set()).add(key)\n        self.document_terms[key]=set(terms)",
    "for term in self.document_terms.get(key,set()):\n            self.postings[term].discard(key)\n            if not self.postings[term]: del self.postings[term]\n        for term in terms: self.postings.setdefault(term,set()).add(key)\n        self.document_terms[key]=set(terms)",
)
SERVICE_FIX = (
    "service.py",
    "self.store.put(document)\n        terms=prepare(document)\n        self.index.replace(document.key,terms)",
    "terms=prepare(document)\n        self.store.put(document)\n        self.index.replace(document.key,terms)",
)
case(
    112,
    "search-projections",
    "Search results and term facets can disagree after document edits or deletion. A rejected edit should "
    "leave the previous document and all search views intact.",
    """Documents have a nonempty string key/title and string body. Search is a case-insensitive intersection
 of whitespace-separated word tokens (letters/digits only); repeated words count once per document.
 Replacing a document removes obsolete terms, and deletion removes all postings. Facets count documents
 containing each term, not token occurrences. Validation failures must leave document storage and index
 projections unchanged. Empty queries return no results; export order is by document key.""",
    {
        "documents.py": """
    from dataclasses import dataclass
    @dataclass(frozen=True)
    class Document:
        key:str
        title:str
        body:str=''
    """,
        "tokenization.py": """
    import re
    def tokens(text): return set(re.findall(r'[^\\W_]+',text.lower()))
    def prepare(document):
        if not isinstance(document.key,str) or not document.key or not isinstance(document.title,str) or not document.title.strip() or not isinstance(document.body,str): raise ValueError('document')
        return tokens(document.title+' '+document.body)
    """,
        "storage.py": """
    class Store:
        def __init__(self): self.documents={}
        def put(self,document): self.documents[document.key]=document
        def remove(self,key): self.documents.pop(key,None)
        def get(self,key): return self.documents[key]
    """,
        "indexing.py": """
    class Index:
        def __init__(self): self.postings={};self.document_terms={}
        def replace(self,key,terms):
            for term in terms: self.postings.setdefault(term,set()).add(key)
            self.document_terms[key]=set(terms)
        def remove(self,key):
            for term in self.document_terms.pop(key,set()):
                self.postings[term].discard(key)
                if not self.postings[term]: del self.postings[term]
    """,
        "query.py": """
    from tokenization import tokens
    def search(store,index,text):
        terms=tokens(text)
        if not terms: return []
        matches=set.intersection(*(set(index.postings.get(term,set())) for term in terms))
        return [store.get(key) for key in sorted(matches)]
    """,
        "facets.py": """
    def counts(index): return {term:len(keys) for term,keys in sorted(index.postings.items())}
    def vocabulary(index): return tuple(sorted(index.postings))
    """,
        "service.py": """
    from tokenization import prepare
    from query import search
    from facets import counts
    class Search:
        def __init__(self,store,index): self.store,self.index=store,index
        def put(self,document):
            self.store.put(document)
            terms=prepare(document)
            self.index.replace(document.key,terms)
        def delete(self,key): self.index.remove(key);self.store.remove(key)
        def find(self,text): return search(self.store,self.index,text)
        def facets(self): return counts(self.index)
    """,
    },
    [INDEX_FIX, SERVICE_FIX],
    r"""import unittest
from documents import Document
from storage import Store
from indexing import Index
from service import Search
class SearchTest(unittest.TestCase):
    def test_normal(self):
        s=Search(Store(),Index());s.put(Document('a','Red apple'))
        self.assertEqual([d.key for d in s.find('APPLE')],['a'])
    def test_replacement(self):
        s=Search(Store(),Index());s.put(Document('a','Red apple'));s.put(Document('a','Blue berry'))
        self.assertEqual(s.find('red'),[])
""",
    r"""from documents import Document
from storage import Store
from indexing import Index
from service import Search
class Contract(unittest.TestCase):
    def build(self): return Search(Store(),Index())
    def test_replace_repairs_all_projections(self):
        s=self.build();s.put(Document('a','Red apple'));s.put(Document('a','Blue berry'))
        self.assertEqual(s.find('red'),[]);self.assertNotIn('red',s.index.postings)
        self.assertEqual(s.facets(),{'berry':1,'blue':1})
    def test_invalid_edit_is_atomic(self):
        s=self.build();original=Document('a','Red apple');s.put(original)
        with self.assertRaises(ValueError): s.put(Document('a',''))
        self.assertEqual(s.store.get('a'),original);self.assertEqual(s.facets(),{'apple':1,'red':1})
    def test_delete_after_update(self):
        s=self.build();s.put(Document('a','red'));s.put(Document('a','blue'));s.delete('a')
        self.assertEqual(s.facets(),{});self.assertEqual(s.index.document_terms,{})
        self.assertEqual(s.find('red'),[]);self.assertEqual(s.find('blue'),[])
    def test_intersection_and_document_counts(self):
        s=self.build();s.put(Document('b','red apple apple'));s.put(Document('a','red berry'))
        self.assertEqual([d.key for d in s.find('red')],['a','b'])
        self.assertEqual([d.key for d in s.find('red apple')],['b']);self.assertEqual(s.facets()['apple'],1)
    def test_empty_and_missing_delete(self):
        s=self.build();s.delete('missing');self.assertEqual(s.find(''),[]);self.assertEqual(s.facets(),{})
""",
    "Replacement only appends new postings instead of removing the previous projection, and storage is committed before the replacement document is validated.",
    [
        "service.py",
        "documents.py",
        "tokenization.py",
        "storage.py",
        "indexing.py",
        "query.py",
        "facets.py",
    ],
    [
        "replace removes obsolete postings",
        "facets and search share one projection",
        "validation before mutation",
        "deletion clears every term",
    ],
    [
        (
            "query.py",
            "return [store.get(key) for key in sorted(matches)]",
            "return [store.get(key) for key in sorted(matches) if terms <= tokens(store.get(key).title+' '+store.get(key).body)]",
        )
    ],
    {
        "documents.py": "Document value model",
        "tokenization.py": "Validation and normalized vocabulary",
        "storage.py": "Primary document records",
        "indexing.py": "Inverted postings and reverse membership",
        "query.py": "Intersection query execution",
        "facets.py": "Document-frequency projections",
        "service.py": "Mutation/query coordination",
    },
)

# Plausible partial repairs: pass the public reproducer but fail private invariants.
CASES[2]["mutant"] = {
    "consumer.py": CASES[2]["reference"]["consumer.py"].replace(
        "            self.broker.ack(message)\n            return 'duplicate'",
        "            return 'duplicate'",
    )
}
CASES[2]["hidden"] = CASES[2]["hidden"].replace(
    "self.assertEqual(len(c.store.audit),1)",
    "self.assertEqual(len(c.store.audit),1);self.assertEqual(c.broker.pending,[])",
)
CASES[5]["mutant"] = {
    "synchronizer.py": CASES[5]["modules"]["synchronizer.py"]
    .replace(
        "from decoding import decode",
        "from decoding import decode\nfrom protocol import BatchError",
    )
    .replace(
        "            self.sink.apply(products)",
        "            try: self.sink.apply(products)\n            except BatchError:\n                self.checkpoint.cursor=None;self.checkpoint.complete=False\n                raise",
    )
}

CASES[0]["hidden"] += """
    def test_account_and_key_delimiters_do_not_alias(self):
        g,a,s=self.build()
        s.submit('a:b','c',5)
        s.submit('a','b:c',7)
        self.assertEqual(len(g.charges),2)
"""

CASES[7]["mutant"] = {
    "resolver.py": CASES[7]["reference"]["resolver.py"],
    "layers.py": CASES[7]["modules"]["layers.py"]
    .replace("result=base", "result=base.copy()")
    .replace("        if not value: continue\n", ""),
}
CASES[10]["mutant"] = {
    "loader.py": CASES[10]["reference"]["loader.py"].replace(
        "            definition=self.registry.get(key)",
        "            try: definition=self.registry.get(key)\n            except KeyError:\n                self.instances[key]=None\n                raise",
    )
}
