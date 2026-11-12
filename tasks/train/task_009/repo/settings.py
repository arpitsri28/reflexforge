from parsing import boolean
def load(mapping):
    return {'debug': boolean(mapping.get('DEBUG', False))}
