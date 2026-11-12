import json
def export(totals): return json.dumps(totals.rows(),sort_keys=True)
