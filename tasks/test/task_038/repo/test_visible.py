import registry
registry.load_defaults()
assert registry.run('double', 4) == 8
