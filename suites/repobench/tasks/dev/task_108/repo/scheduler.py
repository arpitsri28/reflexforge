class Scheduler:
    def __init__(self,config): self.config=config;self.runs=[]
    def tick(self,time):
        interval=self.config['interval']
        if interval and time%interval==0: self.runs.append(time);return True
        return False
