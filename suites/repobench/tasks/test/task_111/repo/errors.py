class DependencyCycle(ValueError):
    @property
    def path(self): return tuple(str(self).split(' -> '))
