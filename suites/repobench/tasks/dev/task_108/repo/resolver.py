from defaults import DEFAULTS
from layers import merge
def resolve(file,environment,cli):
    result=DEFAULTS
    for layer in (file,cli,environment): result=merge(result,layer)
    if type(result['mail']['enabled']) is not bool: raise ValueError('mail enabled')
    if type(result['jobs']['interval']) is not int or result['jobs']['interval']<0: raise ValueError('interval')
    return result
