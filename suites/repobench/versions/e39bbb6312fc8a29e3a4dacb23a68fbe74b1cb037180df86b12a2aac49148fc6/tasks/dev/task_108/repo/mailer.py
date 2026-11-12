class Mailer:
    def __init__(self,config): self.config=config;self.sent=[]
    def send(self,message):
        if not self.config['enabled']: return False
        self.sent.append((self.config['host'],message));return True
