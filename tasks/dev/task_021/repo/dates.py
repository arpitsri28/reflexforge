from datetime import datetime, timezone
def parse(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None: raise ValueError('timezone required')
    return result
