import csv,io,json
def csv_rows(text): return list(csv.DictReader(io.StringIO(text)))
def json_rows(text): return json.loads(text)
