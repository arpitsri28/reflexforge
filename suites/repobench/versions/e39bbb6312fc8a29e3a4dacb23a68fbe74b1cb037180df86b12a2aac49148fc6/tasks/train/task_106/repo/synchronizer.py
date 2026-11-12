from decoding import decode
class Synchronizer:
    def __init__(self,client,checkpoint,sink): self.client,self.checkpoint,self.sink=client,checkpoint,sink
    def run(self,max_pages=None):
        pages,processed=0,0
        while not self.checkpoint.complete and (max_pages is None or pages<max_pages):
            page=self.client.page(self.checkpoint.cursor)
            self.checkpoint.advance(page['next'])
            products=decode(page)
            self.sink.apply(products)
            processed+=len(products)
            pages+=1
        return processed
