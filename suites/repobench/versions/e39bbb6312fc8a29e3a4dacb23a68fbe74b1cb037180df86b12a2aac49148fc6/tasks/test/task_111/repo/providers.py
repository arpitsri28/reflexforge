def value(dependencies,options): return {'value':options['value']}
def bundle(dependencies,options): return {'services':dict(dependencies),'label':options.get('label','bundle')}
def install(factories):
    factories.register('value',value);factories.register('bundle',bundle)
