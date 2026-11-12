"""Authoring data only. Never imports or executes fixture source on the host.

Unique repository contracts are grouped by family. Reference overlays are private
controller inputs, never copied into worker repositories.
"""

from textwrap import dedent

CASES = []


def add(
    number, family, category, difficulty, issue, files, replacements, visible, hidden, coverage
):
    files = {name: dedent(content).lstrip("\n") for name, content in files.items()}
    fixed = dict(files)
    for name, before, after in replacements:
        if before not in fixed[name]:
            raise ValueError(f"{number}: replacement missing in {name}")
        fixed[name] = fixed[name].replace(before, after)
    CASES.append(
        dict(
            number=number,
            family=family,
            category=category,
            difficulty=difficulty,
            issue=issue,
            files=files,
            reference={n: c for n, c in fixed.items() if c != files[n]},
            visible=dedent(visible).lstrip("\n"),
            hidden=dedent(hidden).lstrip("\n"),
            coverage=coverage,
        )
    )


add(
    4,
    "inventory-reservations",
    "state",
    "medium",
    "Inventory availability must subtract all active reservations. Cancelling a reservation restores availability; "
    "overselling must raise ValueError without changing existing reservations. Two carts can currently reserve the same stock.",
    {
        "stock.py": """
        class Stock:
            def __init__(self, quantity):
                self.quantity = quantity
                self.reservations = {}
            def available(self):
                return self.quantity
            def reserve(self, cart, count):
                if count <= 0 or cart in self.reservations or count > self.available():
                    raise ValueError('unavailable')
                self.reservations[cart] = count
            def cancel(self, cart):
                self.reservations.pop(cart, None)
        """,
        "checkout.py": """
        def add_cart(stock, cart, count):
            stock.reserve(cart, count)
            return stock.available()
        """,
    },
    [
        (
            "stock.py",
            "return self.quantity",
            "return self.quantity - sum(self.reservations.values())",
        )
    ],
    r"""from stock import Stock
from checkout import add_cart
s = Stock(5)
assert add_cart(s, 'a', 3) == 2
""",
    r"""from stock import Stock
from checkout import add_cart
s = Stock(5)
assert add_cart(s, 'a', 3) == 2
try: add_cart(s, 'b', 3)
except ValueError: pass
else: raise AssertionError('oversold')
assert s.reservations == {'a': 3}
s.cancel('a')
assert s.available() == 5
s.cancel('missing')
assert s.available() == 5
""",
    ["overlapping carts", "atomic rejection", "cancellation"],
)

add(
    5,
    "tenant-cache-identity",
    "cache",
    "medium",
    "ProfileCache must isolate users across tenants, and invalidate only the selected tenant/user. "
    "Identical user IDs currently leak a cached profile between tenants.",
    {
        "cache.py": """
        class ProfileCache:
            def __init__(self): self.values = {}
            def key(self, tenant, user): return user
            def get(self, tenant, user, loader):
                key = self.key(tenant, user)
                if key not in self.values: self.values[key] = loader(tenant, user)
                return self.values[key]
            def invalidate(self, tenant, user):
                self.values.pop(self.key(tenant, user), None)
        """,
        "profiles.py": """
        def load_profile(tenant, user):
            return {'tenant': tenant, 'user': user}
        """,
    },
    [("cache.py", "return user", "return (tenant, user)")],
    r"""from cache import ProfileCache
from profiles import load_profile
c = ProfileCache()
c.get('red', '42', load_profile)
assert c.get('blue', '42', load_profile)['tenant'] == 'blue'
""",
    r"""from cache import ProfileCache
from profiles import load_profile
c = ProfileCache()
a = c.get('red', '42', load_profile)
b = c.get('blue', '42', load_profile)
assert a['tenant'] == 'red' and b['tenant'] == 'blue'
assert c.get('red', '42', load_profile) is a
c.invalidate('red', '42')
assert c.get('red', '42', load_profile) is not a
assert c.get('blue', '42', load_profile) is b
""",
    ["tenant separation", "cache hit", "scoped invalidation"],
)

add(
    6,
    "directory-invalidation",
    "cache",
    "medium",
    "Updating or deleting a directory entry must invalidate the memoized listing. Cached lists returned to callers "
    "must not be mutable aliases of internal cache state. Entry names are unique.",
    {
        "directory.py": """
        class Directory:
            def __init__(self):
                self.entries = {}
                self.cached = None
            def put(self, name, value):
                self.entries[name] = value
            def delete(self, name):
                self.entries.pop(name, None)
            def listing(self):
                if self.cached is None: self.cached = sorted(self.entries)
                return self.cached
        """,
        "ui.py": """
        def render(directory):
            return ','.join(directory.listing())
        """,
    },
    [
        (
            "directory.py",
            "self.entries[name] = value",
            "self.entries[name] = value\n        self.cached = None",
        ),
        (
            "directory.py",
            "self.entries.pop(name, None)",
            "self.entries.pop(name, None)\n        self.cached = None",
        ),
        ("directory.py", "return self.cached", "return list(self.cached)"),
    ],
    r"""from directory import Directory
from ui import render
d = Directory()
d.put('a', 1)
assert render(d) == 'a'
d.put('b', 2)
assert render(d) == 'a,b'
""",
    r"""from directory import Directory
from ui import render
d = Directory()
assert d.listing() == []
d.put('b', 2)
d.put('a', 1)
assert render(d) == 'a,b'
d.listing().append('fake')
assert render(d) == 'a,b'
d.delete('a')
assert render(d) == 'b'
""",
    ["insert invalidation", "delete invalidation", "defensive copies"],
)

add(
    7,
    "async-ordered-collection",
    "async",
    "hard",
    "collect() must await the fetch coroutine once per input and return values in input order, including empty input. "
    "The current pipeline returns coroutine objects instead of resolved values.",
    {
        "collector.py": """
        async def collect(items, fetch):
            return [fetch(item) for item in items]
        """,
        "pipeline.py": """
        from collector import collect
        async def total(items, fetch):
            values = await collect(items, fetch)
            return sum(values)
        """,
    },
    [
        (
            "collector.py",
            "return [fetch(item) for item in items]",
            "return [await fetch(item) for item in items]",
        )
    ],
    r"""import asyncio
from pipeline import total
async def fetch(x): return x * 2
assert asyncio.run(total([1, 2], fetch)) == 6
""",
    r"""import asyncio
from collector import collect
from pipeline import total
async def check():
    seen = []
    async def fetch(x):
        seen.append(x)
        return x * 2
    assert await collect([3, 1, 2], fetch) == [6, 2, 4]
    assert seen == [3, 1, 2]
    assert await collect([], fetch) == []
    assert await total([4], fetch) == 8
asyncio.run(check())
""",
    ["awaiting", "order and multiplicity", "empty input"],
)

add(
    8,
    "retry-error-taxonomy",
    "retry",
    "medium",
    "retry() may retry TimeoutError only, up to attempts total calls. Other exceptions must propagate immediately. "
    "Exhausted timeouts must propagate the last TimeoutError; attempts below 1 raise ValueError before calling.",
    {
        "retrying.py": """
        def retry(operation, attempts):
            if attempts < 1: raise ValueError('attempts')
            last = None
            for _ in range(attempts):
                try: return operation()
                except Exception as exc: last = exc
            raise last
        """,
        "client.py": """
        from retrying import retry
        def request(operation):
            return retry(operation, 3)
        """,
    },
    [("retrying.py", "except Exception as exc", "except TimeoutError as exc")],
    r"""from client import request
calls = []
def bad():
    calls.append(1)
    raise ValueError('bad request')
try: request(bad)
except ValueError: pass
assert len(calls) == 1
""",
    r"""from retrying import retry
calls = []
def transient():
    calls.append(1)
    if len(calls) < 3: raise TimeoutError('later')
    return 'ok'
assert retry(transient, 3) == 'ok'
assert len(calls) == 3
calls.clear()
def invalid():
    calls.append(1)
    raise ValueError('bad')
try: retry(invalid, 3)
except ValueError: pass
assert len(calls) == 1
calls.clear()
try: retry(invalid, 0)
except ValueError: pass
assert calls == []
""",
    ["transient recovery", "permanent error propagation", "invalid attempt count"],
)

add(
    9,
    "strict-env-booleans",
    "configuration",
    "medium",
    "Settings debug accepts booleans or case-insensitive strings true/false/1/0 with surrounding whitespace. "
    "Other values raise ValueError. The string false currently enables debug.",
    {
        "parsing.py": """
        def boolean(value):
            return bool(value)
        """,
        "settings.py": """
        from parsing import boolean
        def load(mapping):
            return {'debug': boolean(mapping.get('DEBUG', False))}
        """,
    },
    [
        (
            "parsing.py",
            "return bool(value)",
            """if isinstance(value, bool): return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ('true', '1'): return True
        if value in ('false', '0'): return False
    raise ValueError('invalid boolean')""",
        )
    ],
    r"""from settings import load
assert load({'DEBUG': 'false'}) == {'debug': False}
""",
    r"""from settings import load
assert load({'DEBUG': ' FALSE '})['debug'] is False
assert load({'DEBUG': '1'})['debug'] is True
assert load({})['debug'] is False
for bad in ['yes', '', 7]:
    try: load({'DEBUG': bad})
    except ValueError: pass
    else: raise AssertionError('invalid value accepted')
""",
    ["normalization", "defaults", "invalid inputs"],
)

add(
    10,
    "decimal-wire-format",
    "serialization",
    "medium",
    "Money JSON serialization must round-trip Decimal exactly using a decimal string for amount. "
    "The currency field must survive. Large or high-precision amounts currently lose digits.",
    {
        "money.py": """
        from decimal import Decimal
        class Money:
            def __init__(self, amount, currency):
                self.amount = Decimal(amount)
                self.currency = currency
        """,
        "wire.py": """
        import json
        from money import Money
        def encode(money):
            return json.dumps({'amount': float(money.amount), 'currency': money.currency})
        def decode(data):
            fields = json.loads(data)
            return Money(fields['amount'], fields['currency'])
        """,
    },
    [("wire.py", "float(money.amount)", "str(money.amount)")],
    r"""from money import Money
from wire import encode, decode
m = Money('9007199254740993.01', 'CAD')
assert decode(encode(m)).amount == m.amount
""",
    r"""import json
from money import Money
from wire import encode, decode
for value in ['9007199254740993.01', '0.00000000000000001', '-12.30']:
    m = Money(value, 'CAD')
    data = encode(m)
    assert isinstance(json.loads(data)['amount'], str)
    restored = decode(data)
    assert restored.amount == m.amount and restored.currency == 'CAD'
""",
    ["precision", "negative and fractional amounts", "wire type"],
)

add(
    11,
    "document-acl-intersection",
    "authorization",
    "medium",
    "A user may edit a document only if they belong to the document organization AND are its owner or an admin. "
    "Being an admin in another organization must not grant access. authorize() raises PermissionError on denial.",
    {
        "policy.py": """
        def can_edit(user, doc):
            return user['org'] == doc['org'] and user['id'] == doc['owner'] or user['admin']
        """,
        "service.py": """
        from policy import can_edit
        def authorize(user, doc):
            if not can_edit(user, doc): raise PermissionError('denied')
            return doc['id']
        """,
    },
    [
        (
            "policy.py",
            "user['org'] == doc['org'] and user['id'] == doc['owner'] or user['admin']",
            "user['org'] == doc['org'] and (user['id'] == doc['owner'] or user['admin'])",
        )
    ],
    r"""from policy import can_edit
assert not can_edit({'org': 'a', 'id': 1, 'admin': True}, {'org': 'b', 'owner': 2})
""",
    r"""from service import authorize
from policy import can_edit
doc = {'org': 'a', 'owner': 1, 'id': 'doc'}
assert authorize({'org': 'a', 'id': 1, 'admin': False}, doc) == 'doc'
assert can_edit({'org': 'a', 'id': 2, 'admin': True}, doc)
assert not can_edit({'org': 'b', 'id': 1, 'admin': True}, doc)
assert not can_edit({'org': 'a', 'id': 2, 'admin': False}, doc)
""",
    ["organization boundary", "owner/admin privileges", "ordinary member denial"],
)

add(
    12,
    "package-relative-import",
    "imports",
    "medium",
    "The installed-style package shop must expose total() via shop.orders without relying on a top-level prices "
    "module or the current directory containing package internals. Quantities are nonnegative integers.",
    {
        "shop/__init__.py": "",
        "shop/prices.py": "PRICES = {'pen': 3, 'book': 7}\n",
        "shop/orders.py": """
        from prices import PRICES
        def total(lines):
            return sum(PRICES[name] * count for name, count in lines)
        """,
    },
    [("shop/orders.py", "from prices import PRICES", "from .prices import PRICES")],
    r"""from shop.orders import total
assert total([('pen', 2)]) == 6
""",
    r"""from shop.orders import total
assert total([]) == 0
assert total([('pen', 2), ('book', 1)]) == 13
assert total([('book', 0)]) == 0
try: total([('missing', 1)])
except KeyError: pass
else: raise AssertionError('unknown product must fail')
""",
    ["package import", "multiple lines", "unknown product propagation"],
)

add(
    13,
    "stream-consumption",
    "pipeline",
    "medium",
    "summarize() accepts a one-shot iterable of numeric amounts and returns count and total after dropping None. "
    "The generator is currently exhausted when computing the second aggregate.",
    {
        "cleaning.py": """
        def clean(values):
            return (value for value in values if value is not None)
        """,
        "summary.py": """
        from cleaning import clean
        def summarize(values):
            selected = clean(values)
            count = sum(1 for _ in selected)
            return {'count': count, 'total': sum(selected)}
        """,
    },
    [("summary.py", "selected = clean(values)", "selected = list(clean(values))")],
    r"""from summary import summarize
assert summarize(iter([2, None, 3])) == {'count': 2, 'total': 5}
""",
    r"""from summary import summarize
assert summarize(iter([2, None, 3])) == {'count': 2, 'total': 5}
assert summarize(iter([])) == {'count': 0, 'total': 0}
assert summarize([0, -2, None]) == {'count': 2, 'total': -2}
""",
    ["one-shot iteration", "empty input", "zero and negative values"],
)

add(
    14,
    "session-exception-cleanup",
    "lifecycle",
    "medium",
    "session(factory) must close the acquired connection exactly once on normal and exceptional exits. "
    "Do not suppress exceptions from the body, and do not attempt cleanup if acquisition fails.",
    {
        "session.py": """
        from contextlib import contextmanager
        @contextmanager
        def session(factory):
            connection = factory()
            yield connection
            connection.close()
        """,
        "work.py": """
        from session import session
        def execute(factory, operation):
            with session(factory) as connection:
                return operation(connection)
        """,
    },
    [
        (
            "session.py",
            "yield connection\n    connection.close()",
            "try:\n        yield connection\n    finally:\n        connection.close()",
        )
    ],
    r"""from work import execute
class Connection:
    closed = 0
    def close(self): self.closed += 1
c = Connection()
def fail(c): raise ValueError('body')
try: execute(lambda: c, fail)
except ValueError: pass
assert c.closed == 1
""",
    r"""from work import execute
class Connection:
    def __init__(self): self.closed = 0
    def close(self): self.closed += 1
c = Connection()
assert execute(lambda: c, lambda c: 42) == 42
assert c.closed == 1
c = Connection()
def fail(c): raise ValueError('body')
try: execute(lambda: c, fail)
except ValueError as e: assert str(e) == 'body'
else: raise AssertionError('exception suppressed')
assert c.closed == 1
""",
    ["success cleanup", "exception cleanup", "propagation"],
)

add(
    15,
    "cursor-termination",
    "pagination",
    "hard",
    "API collect() must follow opaque next_cursor values until the field is None. An empty item page with a "
    "non-None cursor is not the end. Preserve item order and reject repeated cursors with ValueError rather than looping.",
    {
        "pages.py": """
        def collect(fetch):
            cursor, seen, result = None, set(), []
            while True:
                page = fetch(cursor)
                result.extend(page['items'])
                cursor = page['next_cursor']
                if not page['items']: break
                if cursor in seen: raise ValueError('cursor cycle')
                seen.add(cursor)
            return result
        """,
        "client.py": """
        from pages import collect
        def values(fetch): return [row['value'] for row in collect(fetch)]
        """,
    },
    [("pages.py", "if not page['items']: break", "if cursor is None: break")],
    r"""from client import values
pages = {None: {'items': [], 'next_cursor': 'a'}, 'a': {'items': [{'value': 7}], 'next_cursor': None}}
assert values(pages.__getitem__) == [7]
""",
    r"""from client import values
pages = {None: {'items': [], 'next_cursor': 'a'}, 'a': {'items': [{'value': 7}], 'next_cursor': None}}
assert values(pages.__getitem__) == [7]
assert values(lambda c: {'items': [{'value': 2}], 'next_cursor': None}) == [2]
try: values(lambda c: {'items': [], 'next_cursor': 'same'})
except ValueError: pass
else: raise AssertionError('cycle not rejected')
""",
    ["empty intermediate page", "terminal nonempty page", "cursor cycles"],
)

add(
    16,
    "tree-traversal-validation",
    "validation",
    "hard",
    "Dependency expansion must return each dependency before its dependent, include shared nodes once, and reject "
    "cycles with ValueError. Unknown dependency names should still raise KeyError.",
    {
        "graph.py": """
        def expand(graph, root):
            ordered, visited = [], set()
            def visit(node):
                if node in visited: return
                visited.add(node)
                for dependency in graph[node]: visit(dependency)
                ordered.append(node)
            visit(root)
            return ordered
        """,
        "build.py": """
        from graph import expand
        def plan(graph, target): return tuple(expand(graph, target))
        """,
    },
    [
        ("graph.py", "ordered, visited = [], set()", "ordered, visited, active = [], set(), set()"),
        (
            "graph.py",
            "if node in visited: return\n        visited.add(node)",
            "if node in active: raise ValueError('cycle')\n        if node in visited: return\n        active.add(node)",
        ),
        (
            "graph.py",
            "ordered.append(node)",
            "active.remove(node)\n        visited.add(node)\n        ordered.append(node)",
        ),
    ],
    r"""from build import plan
try: plan({'a': ['b'], 'b': ['a']}, 'a')
except ValueError: pass
else: raise AssertionError('cycle accepted')
""",
    r"""from build import plan
assert plan({'a': ['b', 'c'], 'b': ['d'], 'c': ['d'], 'd': []}, 'a') == ('d', 'b', 'c', 'a')
assert plan({'a': []}, 'a') == ('a',)
try: plan({'a': ['a']}, 'a')
except ValueError: pass
else: raise AssertionError('self cycle accepted')
try: plan({'a': ['missing']}, 'a')
except KeyError: pass
else: raise AssertionError('missing node swallowed')
""",
    ["shared dependencies", "cycle and self-cycle", "unknown nodes"],
)

add(
    17,
    "idempotency-replay",
    "state",
    "hard",
    "Payment submission must charge once per idempotency key and return the original receipt for a replay. "
    "Reusing a key with a different amount must raise ValueError without charging. Failed charges must not reserve a key.",
    {
        "payments.py": """
        class Payments:
            def __init__(self, charge):
                self.charge = charge
                self.receipts = {}
            def submit(self, key, amount):
                receipt = self.charge(amount)
                self.receipts[key] = (amount, receipt)
                return receipt
        """,
        "api.py": """
        def pay(service, request):
            return service.submit(request['key'], request['amount'])
        """,
    },
    [
        (
            "payments.py",
            "receipt = self.charge(amount)",
            "if key in self.receipts:\n            old_amount, receipt = self.receipts[key]\n            if old_amount != amount: raise ValueError('conflicting replay')\n            return receipt\n        receipt = self.charge(amount)",
        )
    ],
    r"""from payments import Payments
from api import pay
calls = []
p = Payments(lambda amount: calls.append(amount) or len(calls))
assert pay(p, {'key': 'a', 'amount': 10}) == pay(p, {'key': 'a', 'amount': 10})
assert calls == [10]
""",
    r"""from payments import Payments
calls = []
p = Payments(lambda amount: calls.append(amount) or len(calls))
assert p.submit('a', 10) == p.submit('a', 10)
assert calls == [10]
try: p.submit('a', 20)
except ValueError: pass
else: raise AssertionError('conflict accepted')
assert calls == [10]
assert p.submit('b', 20) == 2
attempts = []
def fail(amount):
    attempts.append(amount)
    raise RuntimeError('declined')
f = Payments(fail)
for _ in range(2):
    try: f.submit('a', 1)
    except RuntimeError: pass
assert attempts == [1, 1] and f.receipts == {}
""",
    ["safe replay", "conflicting request", "failure not cached"],
)

add(
    18,
    "nested-transaction-snapshot",
    "state",
    "hard",
    "A transaction returns a committed nested dictionary on success and restores the entire dictionary on exception. "
    "A shallow snapshot currently leaves nested list mutations behind after rollback; propagate the body exception.",
    {
        "transactions.py": """
        from contextlib import contextmanager
        @contextmanager
        def transaction(data):
            original = data.copy()
            try: yield data
            except Exception:
                data.clear()
                data.update(original)
                raise
        """,
        "service.py": """
        from transactions import transaction
        def append(data, value, fail=False):
            with transaction(data):
                data['items'].append(value)
                if fail: raise ValueError('rollback')
            return data
        """,
    },
    [
        (
            "transactions.py",
            "from contextlib import contextmanager",
            "from contextlib import contextmanager\nfrom copy import deepcopy",
        ),
        ("transactions.py", "original = data.copy()", "original = deepcopy(data)"),
    ],
    r"""from service import append
data = {'items': [1]}
try: append(data, 2, True)
except ValueError: pass
assert data == {'items': [1]}
""",
    r"""from service import append
data = {'items': [1], 'nested': {'flag': True}}
assert append(data, 2) is data
assert data['items'] == [1, 2]
try: append(data, 3, True)
except ValueError: pass
else: raise AssertionError('error swallowed')
assert data == {'items': [1, 2], 'nested': {'flag': True}}
""",
    ["nested rollback", "commit", "exception propagation"],
)

add(
    19,
    "stable-priority-merge",
    "sorting",
    "medium",
    "merge() should combine sources and order by descending priority while preserving encounter order on equal "
    "priority. Priority zero is valid. Source data must not be mutated.",
    {
        "ordering.py": """
        def merge(sources):
            rows = [dict(row) for source in sources for row in source]
            return sorted(rows, key=lambda row: (row['priority'], row['id']), reverse=True)
        """,
        "dashboard.py": """
        from ordering import merge
        def ids(sources): return [r['id'] for r in merge(sources)]
        """,
    },
    [("ordering.py", "(row['priority'], row['id'])", "row['priority']")],
    r"""from dashboard import ids
assert ids([[{'id': 'a', 'priority': 2}], [{'id': 'z', 'priority': 2}]]) == ['a', 'z']
""",
    r"""from dashboard import ids
from ordering import merge
a = [{'id': 'a', 'priority': 2}, {'id': 'b', 'priority': 0}]
b = [{'id': 'z', 'priority': 2}, {'id': 'q', 'priority': 3}]
assert ids([a, b]) == ['q', 'a', 'z', 'b']
rows = merge([a])
rows[0]['id'] = 'changed'
assert a[0]['id'] == 'a'
assert ids([]) == []
""",
    ["stable ties", "descending order", "input isolation"],
)

add(
    20,
    "async-shared-counter",
    "concurrency",
    "hard",
    "Counter.increment() must be atomic across async callers. Keep the deliberate scheduling point so the "
    "test reproduces lost updates deterministically; multiple increments must yield unique successive values.",
    {
        "counter.py": """
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
        """,
        "batch.py": """
        import asyncio
        async def run(counter, count):
            return await asyncio.gather(*(counter.increment() for _ in range(count)))
        """,
    },
    [
        (
            "counter.py",
            "before = self.value\n        await asyncio.sleep(0)\n        self.value = before + 1\n        return self.value",
            "async with self.lock:\n            before = self.value\n            await asyncio.sleep(0)\n            self.value = before + 1\n            return self.value",
        )
    ],
    r"""import asyncio
from counter import Counter
from batch import run
async def check():
    c = Counter()
    await run(c, 5)
    assert c.value == 5
asyncio.run(check())
""",
    r"""import asyncio
from counter import Counter
from batch import run
async def check():
    c = Counter()
    assert sorted(await run(c, 8)) == list(range(1, 9))
    assert c.value == 8
    assert await run(c, 0) == []
    assert await c.increment() == 9
asyncio.run(check())
""",
    ["deterministic interleaving", "unique increments", "empty batch and reuse"],
)

# Development repositories: distinct implementation families, not renamed train bugs.
add(
    21,
    "timezone-normalization",
    "datetime",
    "hard",
    "Event timestamps accept ISO-8601 offsets or Z. Normalize parsed timestamps to UTC; sort by actual instant, "
    "not lexicographic text. Equivalent instants retain input order; a timestamp without timezone raises ValueError.",
    {
        "dates.py": """
        from datetime import datetime, timezone
        def parse(value):
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if result.tzinfo is None: raise ValueError('timezone required')
            return result
        """,
        "events.py": """
        from dates import parse
        def ordered(records):
            return sorted(records, key=lambda r: r['time'])
        def utc_time(record): return parse(record['time']).isoformat()
        """,
    },
    [
        ("dates.py", "return result", "return result.astimezone(timezone.utc)"),
        ("events.py", "key=lambda r: r['time']", "key=lambda r: parse(r['time'])"),
    ],
    r"""from events import ordered, utc_time
rows = [{'id': 1, 'time': '2024-01-01T10:00:00+02:00'}, {'id': 2, 'time': '2024-01-01T09:00:00Z'}]
assert [r['id'] for r in ordered(rows)] == [1, 2]
assert utc_time(rows[0]) == '2024-01-01T08:00:00+00:00'
""",
    r"""from events import ordered, utc_time
from dates import parse
rows = [{'id': 1, 'time': '2024-01-01T10:00:00+02:00'}, {'id': 2, 'time': '2024-01-01T09:00:00Z'}]
assert [r['id'] for r in ordered(rows)] == [1, 2]
assert utc_time(rows[0]) == '2024-01-01T08:00:00+00:00'
same = [{'id': 'a', 'time': '2024-01-01T08:00:00Z'}, {'id': 'b', 'time': '2024-01-01T10:00:00+02:00'}]
assert [r['id'] for r in ordered(same)] == ['a', 'b']
try: parse('2024-01-01T10:00:00')
except ValueError: pass
else: raise AssertionError('naive timestamp accepted')
""",
    ["offset normalization", "chronological order", "timezone validation and stable ties"],
)

add(
    22,
    "single-use-login-code",
    "authentication",
    "hard",
    "Login codes expire at now >= expires and are single-use. Successful redemption removes the code. "
    "An invalid or expired code must not produce a session. Use the explicit supplied clock, not wall time.",
    {
        "codes.py": """
        class Codes:
            def __init__(self): self.values = {}
            def issue(self, code, user, expires): self.values[code] = (user, expires)
            def redeem(self, code, now):
                user, expires = self.values[code]
                if now > expires: raise ValueError('expired')
                return user
        """,
        "login.py": """
        def login(codes, code, now):
            return {'session_user': codes.redeem(code, now)}
        """,
    },
    [
        ("codes.py", "if now > expires:", "if now >= expires:"),
        ("codes.py", "return user", "del self.values[code]\n        return user"),
    ],
    r"""from codes import Codes
from login import login
c = Codes()
c.issue('code', 'u', 10)
assert login(c, 'code', 9)['session_user'] == 'u'
assert 'code' not in c.values
""",
    r"""from codes import Codes
from login import login
c = Codes()
c.issue('a', 'u', 10)
assert login(c, 'a', 9) == {'session_user': 'u'}
try: login(c, 'a', 9)
except KeyError: pass
else: raise AssertionError('replayed login')
c.issue('b', 'v', 10)
try: login(c, 'b', 10)
except ValueError: pass
else: raise AssertionError('expiry boundary accepted')
assert c.values['b'] == ('v', 10)
""",
    ["single use", "replay denial", "expiry boundary"],
)

add(
    23,
    "csv-quoted-records",
    "serialization",
    "medium",
    "Read and write CSV rows using standard CSV quoting: embedded commas, double quotes and newlines must "
    "round-trip. Return strings, preserve empty cells, and do not split embedded newlines into records.",
    {
        "codec.py": """
        def encode(rows):
            return '\\n'.join(','.join(row) for row in rows)
        def decode(text):
            return [line.split(',') for line in text.splitlines()]
        """,
        "export.py": """
        from codec import encode, decode
        def transfer(rows): return decode(encode(rows))
        """,
    },
    [
        (
            "codec.py",
            "def encode(rows):\n    return '\\n'.join(','.join(row) for row in rows)\ndef decode(text):\n    return [line.split(',') for line in text.splitlines()]",
            "import csv\nimport io\ndef encode(rows):\n    stream = io.StringIO(newline='')\n    csv.writer(stream).writerows(rows)\n    return stream.getvalue()\ndef decode(text):\n    return list(csv.reader(io.StringIO(text, newline='')))",
        )
    ],
    r"""from export import transfer
assert transfer([['a,b', 'c']]) == [['a,b', 'c']]
""",
    r"""from export import transfer
assert transfer([['a,b', 'c'], ['say "yes"', '']]) == [['a,b', 'c'], ['say "yes"', '']]
assert transfer([['line1\nline2', 'x']]) == [['line1\nline2', 'x']]
assert transfer([]) == []
""",
    ["quoted delimiters", "embedded line breaks", "empty values"],
)

add(
    24,
    "bounded-lru-refresh",
    "cache",
    "medium",
    "LRU hits must refresh recency. Insertion above capacity evicts the least recently used entry; replacing "
    "an existing key must not evict another entry. Capacity is positive.",
    {
        "lru.py": """
        from collections import OrderedDict
        class LRU:
            def __init__(self, capacity):
                self.capacity, self.data = capacity, OrderedDict()
            def get(self, key):
                return self.data[key]
            def put(self, key, value):
                self.data[key] = value
                if len(self.data) > self.capacity: self.data.popitem(last=False)
        """,
        "lookup.py": """
        def fetch(cache, key, loader):
            try: return cache.get(key)
            except KeyError:
                value = loader(key)
                cache.put(key, value)
                return value
        """,
    },
    [
        (
            "lru.py",
            "return self.data[key]",
            "value = self.data[key]\n        self.data.move_to_end(key)\n        return value",
        ),
        (
            "lru.py",
            "self.data[key] = value",
            "self.data[key] = value\n        self.data.move_to_end(key)",
        ),
    ],
    r"""from lru import LRU
from lookup import fetch
c = LRU(2)
c.put('a', 1)
c.put('b', 2)
assert fetch(c, 'a', lambda k: 9) == 1
c.put('c', 3)
assert 'a' in c.data and 'b' not in c.data
""",
    r"""from lru import LRU
from lookup import fetch
c = LRU(2)
c.put('a', 1)
c.put('b', 2)
assert fetch(c, 'a', lambda k: 9) == 1
c.put('c', 3)
assert list(c.data) == ['a', 'c']
c.put('a', 7)
assert list(c.data) == ['c', 'a'] and c.get('a') == 7
assert fetch(c, 'd', lambda k: 4) == 4
assert len(c.data) == 2
""",
    ["hit recency", "replacement recency", "capacity enforcement"],
)

add(
    25,
    "async-failure-cancellation",
    "async",
    "hard",
    "race_fail_fast() must cancel and await unfinished siblings when one child fails, then propagate that "
    "exception. Successful calls return results in input order. Tests use events, not timing-dependent sleeps.",
    {
        "group.py": """
        import asyncio
        async def race_fail_fast(coroutines):
            tasks = [asyncio.create_task(c) for c in coroutines]
            return await asyncio.gather(*tasks)
        """,
        "service.py": """
        from group import race_fail_fast
        async def process(coroutines): return await race_fail_fast(coroutines)
        """,
    },
    [
        (
            "group.py",
            "return await asyncio.gather(*tasks)",
            "try:\n        return await asyncio.gather(*tasks)\n    except BaseException:\n        for task in tasks:\n            if not task.done(): task.cancel()\n        await asyncio.gather(*tasks, return_exceptions=True)\n        raise",
        )
    ],
    r"""import asyncio
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
""",
    r"""import asyncio
from service import process
async def check():
    async def value(x): return x
    assert await process([value(2), value(1)]) == [2, 1]
    assert await process([]) == []
    started, stopped = asyncio.Event(), asyncio.Event()
    async def blocked():
        started.set()
        try: await asyncio.Event().wait()
        finally: stopped.set()
    async def fail():
        await started.wait()
        raise ValueError('failure')
    try: await process([blocked(), fail()])
    except ValueError as exc: assert str(exc) == 'failure'
    else: raise AssertionError('failure swallowed')
    assert stopped.is_set()
asyncio.run(check())
""",
    ["successful gather", "sibling cancellation", "awaited cleanup and propagation"],
)

add(
    26,
    "header-token-boundaries",
    "parsing",
    "medium",
    "Bearer credentials require exactly two whitespace-separated fields, case-insensitive Bearer scheme, "
    "and a nonempty token. Reject extra fields or another scheme with ValueError, preserving token case.",
    {
        "headers.py": """
        def bearer(value):
            return value.split(' ')[1]
        """,
        "request.py": """
        from headers import bearer
        def credentials(headers): return bearer(headers['Authorization'])
        """,
    },
    [
        (
            "headers.py",
            "return value.split(' ')[1]",
            "parts = value.split()\n    if len(parts) != 2 or parts[0].lower() != 'bearer': raise ValueError('invalid authorization')\n    return parts[1]",
        )
    ],
    r"""from request import credentials
try: credentials({'Authorization': 'Basic abc'})
except ValueError: pass
else: raise AssertionError('wrong scheme accepted')
""",
    r"""from request import credentials
assert credentials({'Authorization': 'bearer AbC'}) == 'AbC'
assert credentials({'Authorization': ' Bearer\txyz '}) == 'xyz'
for value in ['Basic abc', 'Bearer', 'Bearer a b', '']:
    try: credentials({'Authorization': value})
    except ValueError: pass
    else: raise AssertionError('invalid header accepted')
""",
    ["scheme validation", "whitespace handling", "field count"],
)

add(
    27,
    "batch-partial-results",
    "errors",
    "medium",
    "Batch processing should collect ValueError failures per input and continue, but propagate infrastructure "
    "RuntimeError immediately. Preserve positional results with None for invalid records and indexed error strings.",
    {
        "batching.py": """
        def process(records, convert):
            values, errors = [], {}
            for index, record in enumerate(records):
                try: values.append(convert(record))
                except Exception as exc:
                    values.append(None)
                    errors[index] = str(exc)
            return values, errors
        """,
        "converters.py": """
        def integer(value):
            if value == 'offline': raise RuntimeError('unavailable')
            return int(value)
        """,
    },
    [("batching.py", "except Exception as exc:", "except ValueError as exc:")],
    r"""from batching import process
from converters import integer
try: process(['offline'], integer)
except RuntimeError: pass
else: raise AssertionError('infrastructure failure hidden')
""",
    r"""from batching import process
from converters import integer
values, errors = process(['1', 'bad', '2'], integer)
assert values == [1, None, 2] and list(errors) == [1]
assert 'bad' in errors[1]
assert process([], integer) == ([], {})
try: process(['1', 'offline', '2'], integer)
except RuntimeError as exc: assert str(exc) == 'unavailable'
else: raise AssertionError('infrastructure error swallowed')
""",
    ["partial results", "error positions", "infrastructure propagation"],
)

add(
    28,
    "settings-layer-merge",
    "configuration",
    "hard",
    "Merge configuration dictionaries recursively, with overrides winning only for supplied keys. "
    "Do not mutate or retain mutable aliases to either input, including nested lists. Scalars replace dictionaries.",
    {
        "merge.py": """
        def combine(base, override):
            result = base.copy()
            result.update(override)
            return result
        """,
        "config.py": """
        from merge import combine
        def resolve(defaults, user): return combine(defaults, user)
        """,
    },
    [
        (
            "merge.py",
            "result = base.copy()\n    result.update(override)\n    return result",
            "from copy import deepcopy\n    result = deepcopy(base)\n    for key, value in override.items():\n        if isinstance(value, dict) and isinstance(result.get(key), dict):\n            result[key] = combine(result[key], value)\n        else: result[key] = deepcopy(value)\n    return result",
        )
    ],
    r"""from config import resolve
assert resolve({'db': {'host': 'local', 'port': 1}}, {'db': {'port': 2}}) == {'db': {'host': 'local', 'port': 2}}
""",
    r"""from config import resolve
base = {'db': {'host': 'local', 'port': 1}, 'tags': ['a']}
override = {'db': {'port': 2}, 'extra': ['x']}
result = resolve(base, override)
assert result['db'] == {'host': 'local', 'port': 2}
result['tags'].append('b')
result['extra'].append('y')
assert base['tags'] == ['a'] and override['extra'] == ['x']
assert resolve({'db': {'port': 1}}, {'db': None})['db'] is None
""",
    ["recursive merge", "input ownership", "scalar replacement"],
)

add(
    29,
    "iterator-window-flush",
    "pipeline",
    "medium",
    "chunks() must yield nonempty batches up to size, including the final partial batch. Accept one-shot iterables; "
    "nonpositive size raises ValueError. export() must preserve every row exactly once.",
    {
        "chunks.py": """
        def chunks(values, size):
            if size <= 0: raise ValueError('size')
            batch = []
            for value in values:
                batch.append(value)
                if len(batch) == size:
                    yield batch
                    batch = []
        """,
        "export.py": """
        from chunks import chunks
        def export(values, size): return list(chunks(values, size))
        """,
    },
    [
        ("chunks.py", "batch = []\n", "batch = []\n"),
        (
            "chunks.py",
            "            batch = []",
            "            batch = []\n    if batch: yield batch",
        ),
    ],
    r"""from export import export
assert export(iter([1, 2, 3]), 2) == [[1, 2], [3]]
""",
    r"""from export import export
assert export(iter([1, 2, 3]), 2) == [[1, 2], [3]]
assert export([], 2) == []
assert export([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
try: export([1], 0)
except ValueError: pass
else: raise AssertionError('invalid size')
""",
    ["partial final batch", "empty/exact batches", "size validation"],
)

add(
    30,
    "resource-stack-order",
    "lifecycle",
    "hard",
    "open_all() acquires resources in input order and closes them in reverse order, including partial acquisition "
    "failure. A body exception must propagate after cleanup. Factories return objects with close().",
    {
        "resources.py": """
        from contextlib import contextmanager
        @contextmanager
        def open_all(factories):
            opened = [factory() for factory in factories]
            try: yield opened
            finally:
                for resource in opened: resource.close()
        """,
        "job.py": """
        from resources import open_all
        def run(factories, operation):
            with open_all(factories) as resources: return operation(resources)
        """,
    },
    [
        (
            "resources.py",
            "opened = [factory() for factory in factories]\n    try: yield opened\n    finally:\n        for resource in opened: resource.close()",
            "opened = []\n    try:\n        for factory in factories: opened.append(factory())\n        yield opened\n    finally:\n        for resource in reversed(opened): resource.close()",
        )
    ],
    r"""from job import run
closed = []
class R:
    def __init__(self, name): self.name = name
    def close(self): closed.append(self.name)
run([lambda: R('a'), lambda: R('b')], lambda rs: len(rs))
assert closed == ['b', 'a']
""",
    r"""from job import run
closed = []
class R:
    def __init__(self, name): self.name = name
    def close(self): closed.append(self.name)
assert run([lambda: R('a'), lambda: R('b')], len) == 2
assert closed == ['b', 'a']
closed.clear()
def fail(): raise ValueError('acquire')
try: run([lambda: R('a'), fail], len)
except ValueError: pass
else: raise AssertionError('acquisition failure hidden')
assert closed == ['a']
assert run([], len) == 0
""",
    ["LIFO teardown", "partial acquisition failure", "empty resource group"],
)

add(
    31,
    "route-parameter-precedence",
    "routing",
    "medium",
    "Router matching must prefer literal paths over parameter routes regardless of registration order. "
    "Parameter routes match exactly one nonempty segment, not extra segments. Unknown routes raise KeyError.",
    {
        "routing.py": """
        class Router:
            def __init__(self): self.routes = []
            def add(self, path, handler): self.routes.append((path, handler))
            def resolve(self, path):
                for route, handler in self.routes:
                    prefix = route.split(':')[0]
                    if route == path or ':' in route and path.startswith(prefix): return handler
                raise KeyError(path)
        """,
        "app.py": """
        from routing import Router
        def create():
            r = Router()
            r.add('/users/:id', 'user')
            r.add('/users/me', 'self')
            return r
        """,
    },
    [
        (
            "routing.py",
            "for route, handler in self.routes:\n            prefix = route.split(':')[0]\n            if route == path or ':' in route and path.startswith(prefix): return handler",
            "for route, handler in self.routes:\n            if ':' not in route and route == path: return handler\n        for route, handler in self.routes:\n            left, right = route.strip('/').split('/'), path.strip('/').split('/')\n            if len(left) == len(right) and all(a == b or a.startswith(':') and bool(b) for a, b in zip(left, right)): return handler",
        )
    ],
    r"""from app import create
assert create().resolve('/users/me') == 'self'
""",
    r"""from app import create
r = create()
assert r.resolve('/users/me') == 'self'
assert r.resolve('/users/42') == 'user'
for path in ['/users/42/edit', '/users/', '/other/42']:
    try: r.resolve(path)
    except KeyError: pass
    else: raise AssertionError('nonmatching route accepted')
""",
    ["literal precedence", "segment boundaries", "unknown paths"],
)

# Held-out families: never used by the optimizer or its meta prompts.
add(
    32,
    "binary-frame-boundaries",
    "protocol",
    "hard",
    "FrameDecoder buffers length-prefixed byte frames (one-byte unsigned length). It must retain partial frames "
    "across feed() calls, emit multiple complete frames, and permit zero-length payloads without losing bytes.",
    {
        "frames.py": """
        class FrameDecoder:
            def __init__(self): self.buffer = b''
            def feed(self, data):
                self.buffer += data
                result = []
                while self.buffer:
                    length = self.buffer[0]
                    if len(self.buffer) < length + 1:
                        self.buffer = b''
                        break
                    result.append(self.buffer[1:length + 1])
                    self.buffer = self.buffer[length + 1:]
                return result
        """,
        "transport.py": """
        def receive(decoder, pieces):
            return [frame for piece in pieces for frame in decoder.feed(piece)]
        """,
    },
    [
        (
            "frames.py",
            "                self.buffer = b''\n                break",
            "                break",
        )
    ],
    r"""from frames import FrameDecoder
from transport import receive
assert receive(FrameDecoder(), [b'\x03a', b'bc']) == [b'abc']
""",
    r"""from frames import FrameDecoder
from transport import receive
d = FrameDecoder()
assert d.feed(b'\x03a') == []
assert d.feed(b'bc\x00\x01x') == [b'abc', b'', b'x']
assert d.feed(b'') == []
assert receive(FrameDecoder(), [b'\x02', b'a', b'b\x01z']) == [b'ab', b'z']
""",
    ["fragment buffering", "multiple/empty frames", "state reuse"],
)

add(
    33,
    "interval-coalescing",
    "algorithms",
    "hard",
    "Normalize half-open intervals by merging overlap and adjacency. Inputs may be unsorted and contain nested "
    "ranges; preserve the maximum end of overlapping intervals. Reject start > end and omit empty intervals.",
    {
        "intervals.py": """
        def coalesce(intervals):
            result = []
            for start, end in sorted(intervals):
                if start > end: raise ValueError('reversed interval')
                if start == end: continue
                if result and start <= result[-1][1]: result[-1] = (result[-1][0], end)
                else: result.append((start, end))
            return result
        """,
        "schedule.py": """
        from intervals import coalesce
        def occupied(intervals): return sum(b - a for a, b in coalesce(intervals))
        """,
    },
    [("intervals.py", "(result[-1][0], end)", "(result[-1][0], max(result[-1][1], end))")],
    r"""from schedule import occupied
assert occupied([(1, 10), (2, 3)]) == 9
""",
    r"""from intervals import coalesce
from schedule import occupied
assert coalesce([(1, 10), (2, 3), (10, 12)]) == [(1, 12)]
assert occupied([(5, 7), (1, 2)]) == 3
assert coalesce([(2, 2)]) == []
try: coalesce([(3, 1)])
except ValueError: pass
else: raise AssertionError('reversed interval')
""",
    ["nested ranges", "adjacency and gaps", "empty/reversed intervals"],
)

add(
    34,
    "schema-version-dispatch",
    "serialization",
    "hard",
    "Reader accepts version 1 documents with full_name and version 2 with first/last, returning canonical name. "
    "Missing version defaults to 1. Unknown versions must raise ValueError, not silently use version 2.",
    {
        "migrations.py": """
        def canonical(fields, version):
            if version == 1: return {'name': fields['full_name']}
            return {'name': fields['first'] + ' ' + fields['last']}
        """,
        "reader.py": """
        import json
        from migrations import canonical
        def read(text):
            document = json.loads(text)
            return canonical(document['data'], document.get('version', 2))
        """,
    },
    [
        (
            "migrations.py",
            "return {'name': fields['first'] + ' ' + fields['last']}",
            "if version == 2: return {'name': fields['first'] + ' ' + fields['last']}\n    raise ValueError('unsupported schema')",
        ),
        ("reader.py", "document.get('version', 2)", "document.get('version', 1)"),
    ],
    r"""from reader import read
assert read('{"data": {"full_name": "Ada Lovelace"}}') == {'name': 'Ada Lovelace'}
""",
    r"""from reader import read
assert read('{"data": {"full_name": "Ada Lovelace"}}') == {'name': 'Ada Lovelace'}
assert read('{"version": 2, "data": {"first": "Grace", "last": "Hopper"}}') == {'name': 'Grace Hopper'}
try: read('{"version": 3, "data": {"first": "x", "last": "y"}}')
except ValueError: pass
else: raise AssertionError('unknown version accepted')
""",
    ["legacy default", "new schema", "unknown schema rejection"],
)

add(
    35,
    "event-subscription-lifecycle",
    "events",
    "medium",
    "Publishing should invoke the subscriptions present at dispatch start once each, even if a callback "
    "unsubscribes itself. New subscriptions begin with the next dispatch. unsubscribe is idempotent.",
    {
        "bus.py": """
        class Bus:
            def __init__(self): self.handlers = []
            def subscribe(self, handler): self.handlers.append(handler)
            def unsubscribe(self, handler):
                if handler in self.handlers: self.handlers.remove(handler)
            def publish(self, value):
                for handler in self.handlers: handler(value)
        """,
        "listeners.py": """
        def once(bus, callback):
            def handler(value):
                bus.unsubscribe(handler)
                callback(value)
            bus.subscribe(handler)
        """,
    },
    [("bus.py", "for handler in self.handlers:", "for handler in tuple(self.handlers):")],
    r"""from bus import Bus
from listeners import once
b, seen = Bus(), []
once(b, lambda x: seen.append(('one', x)))
b.subscribe(lambda x: seen.append(('two', x)))
b.publish(1)
assert seen == [('one', 1), ('two', 1)]
""",
    r"""from bus import Bus
from listeners import once
b, seen = Bus(), []
once(b, lambda x: seen.append(('one', x)))
b.subscribe(lambda x: seen.append(('two', x)))
b.publish(1)
b.publish(2)
assert seen == [('one', 1), ('two', 1), ('two', 2)]
b = Bus()
seen = []
def later(x): seen.append(x)
def adding(x): b.subscribe(later)
b.subscribe(adding)
b.publish(3)
assert seen == []
b.publish(4)
assert seen == [4]
b.unsubscribe(lambda x: None)
""",
    ["self-unsubscribe", "new handlers deferred", "repeated dispatch"],
)

add(
    36,
    "weighted-aggregation",
    "analytics",
    "medium",
    "Aggregate weighted mean across partitions using total weighted sum divided by total weight, not a mean "
    "of partition means. Ignore zero-weight observations; return None when total weight is zero. Weights are nonnegative.",
    {
        "stats.py": """
        def partition(rows):
            weight = sum(w for value, w in rows)
            total = sum(value * w for value, w in rows)
            return total, weight
        """,
        "aggregate.py": """
        from stats import partition
        def mean(partitions):
            summaries = [partition(rows) for rows in partitions]
            means = [total / weight for total, weight in summaries if weight]
            return sum(means) / len(means) if means else None
        """,
    },
    [
        (
            "aggregate.py",
            "means = [total / weight for total, weight in summaries if weight]\n    return sum(means) / len(means) if means else None",
            "total = sum(t for t, w in summaries)\n    weight = sum(w for t, w in summaries)\n    return total / weight if weight else None",
        )
    ],
    r"""from aggregate import mean
assert mean([[(10, 1)], [(20, 3)]]) == 17.5
""",
    r"""from aggregate import mean
assert mean([[(10, 1)], [(20, 3)]]) == 17.5
assert mean([[], [(9, 0)]]) is None
assert mean([[(10, 1), (20, 3)]]) == mean([[(10, 1)], [(20, 3)]])
assert mean([[(-2, 2)], [(2, 2)]]) == 0
""",
    ["partition invariance", "unequal weights", "zero weights"],
)

add(
    37,
    "url-query-multivalue",
    "encoding",
    "medium",
    "URL query construction must percent-encode reserved characters and emit one key=value pair per list item. "
    "Spaces, plus signs, ampersands and Unicode must round-trip with parse_qs. Empty lists emit no values.",
    {
        "query.py": """
        def encode(params):
            return '&'.join(str(k) + '=' + str(v) for k, v in params.items())
        """,
        "links.py": """
        from query import encode
        def search_link(params): return '/search?' + encode(params)
        """,
    },
    [
        (
            "query.py",
            "return '&'.join(str(k) + '=' + str(v) for k, v in params.items())",
            "from urllib.parse import urlencode\n    return urlencode(params, doseq=True)",
        )
    ],
    r"""from urllib.parse import parse_qs
from links import search_link
assert parse_qs(search_link({'q': 'a&b'}) .split('?', 1)[1]) == {'q': ['a&b']}
""",
    r"""from urllib.parse import parse_qs
from links import search_link
def decode(params): return parse_qs(search_link(params).split('?', 1)[1])
assert decode({'q': 'a&b + café'}) == {'q': ['a&b + café']}
assert decode({'tag': ['x', 'y']}) == {'tag': ['x', 'y']}
assert decode({'tag': []}) == {}
""",
    ["reserved characters", "repeated parameters", "Unicode and empty lists"],
)

add(
    38,
    "plugin-registry-lazy-import",
    "imports",
    "hard",
    "Importing the registry must not eagerly import plugin implementations: plugins import registry.register, "
    "which currently causes a circular import. load_defaults() should explicitly import and register the builtin "
    "plugin idempotently. Missing names raise KeyError.",
    {
        "registry.py": """
        import builtin_plugin
        HANDLERS = {}
        def register(name, handler): HANDLERS[name] = handler
        def load_defaults(): return None
        def run(name, value): return HANDLERS[name](value)
        """,
        "builtin_plugin.py": """
        from registry import register
        def double(value): return value * 2
        register('double', double)
        """,
    },
    [
        ("registry.py", "import builtin_plugin\n", ""),
        (
            "registry.py",
            "def load_defaults(): return None",
            "def load_defaults():\n    from builtin_plugin import double\n    register('double', double)",
        ),
    ],
    r"""import registry
registry.load_defaults()
assert registry.run('double', 4) == 8
""",
    r"""import sys
import registry
assert 'builtin_plugin' not in sys.modules
registry.load_defaults()
assert registry.run('double', 4) == 8
registry.load_defaults()
assert len(registry.HANDLERS) == 1
try: registry.run('missing', 1)
except KeyError: pass
else: raise AssertionError('missing plugin accepted')
""",
    ["lazy import", "idempotent initialization", "missing plugin"],
)
