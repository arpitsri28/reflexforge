import json
from schema import validate
def decode(frame): return validate(json.loads(frame.decode('utf-8')))
