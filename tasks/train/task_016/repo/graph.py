def expand(graph, root):
    ordered, visited = [], set()
    def visit(node):
        if node in visited: return
        visited.add(node)
        for dependency in graph[node]: visit(dependency)
        ordered.append(node)
    visit(root)
    return ordered
