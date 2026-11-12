def live(resources): return [r.name for r in resources if r.opened and not r.closed]
def close_order(events): return [name for operation,name in events if operation=='close']
