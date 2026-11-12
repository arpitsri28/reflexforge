from resources import open_all
def run(factories, operation):
    with open_all(factories) as resources: return operation(resources)
