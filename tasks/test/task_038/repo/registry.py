import builtin_plugin
HANDLERS = {}
def register(name, handler): HANDLERS[name] = handler
def load_defaults(): return None
def run(name, value): return HANDLERS[name](value)
