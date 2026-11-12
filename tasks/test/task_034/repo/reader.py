import json
from migrations import canonical
def read(text):
    document = json.loads(text)
    return canonical(document['data'], document.get('version', 2))
