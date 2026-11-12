from dates import parse
def ordered(records):
    return sorted(records, key=lambda r: r['time'])
def utc_time(record): return parse(record['time']).isoformat()
