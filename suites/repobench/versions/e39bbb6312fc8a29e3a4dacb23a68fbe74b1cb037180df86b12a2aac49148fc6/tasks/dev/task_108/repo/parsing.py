def boolean(value):
    if value.lower() in ('true','1'): return True
    if value.lower() in ('false','0'): return False
    raise ValueError('boolean')
def environment(values):
    result={}
    if 'MAIL_ENABLED' in values: result.setdefault('mail',{})['enabled']=boolean(values['MAIL_ENABLED'])
    if 'MAIL_HOST' in values: result.setdefault('mail',{})['host']=values['MAIL_HOST']
    if 'JOB_INTERVAL' in values: result.setdefault('jobs',{})['interval']=int(values['JOB_INTERVAL'])
    return result
