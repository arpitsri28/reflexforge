from sources import csv_rows,json_rows
from aggregation import Totals
from pipeline import Pipeline
from exporting import export
class Application:
    def __init__(self): self.totals=Totals();self.pipeline=Pipeline(self.totals)
    def csv(self,text): return self.pipeline.ingest(csv_rows(text))
    def json(self,text): return self.pipeline.ingest(json_rows(text))
    def report(self): return export(self.totals)
