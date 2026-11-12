def validate_factories(factories):
    if not all(callable(factory) for factory in factories): raise ValueError('resource factory')
    return list(factories)
