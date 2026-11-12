class Router:
    def __init__(self): self.routes = []
    def add(self, path, handler): self.routes.append((path, handler))
    def resolve(self, path):
        for route, handler in self.routes:
            prefix = route.split(':')[0]
            if route == path or ':' in route and path.startswith(prefix): return handler
        raise KeyError(path)
