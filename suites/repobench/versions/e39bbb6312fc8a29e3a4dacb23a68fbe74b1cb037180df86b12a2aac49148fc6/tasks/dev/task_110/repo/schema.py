def validate(event):
    if not isinstance(event,dict) or type(event.get('seq')) is not int or event['seq']<=0: raise ValueError('sequence')
    if event.get('kind') not in ('add','ping'): raise ValueError('kind')
    if event['kind']=='add' and (type(event.get('amount')) is not int or not isinstance(event.get('label'),str)): raise ValueError('add payload')
    return event
