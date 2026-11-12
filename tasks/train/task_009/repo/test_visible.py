from settings import load
assert load({'DEBUG': 'false'}) == {'debug': False}
