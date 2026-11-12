def merge(base,override):
    result=base
    for key,value in override.items():
        if not value: continue
        if isinstance(value,dict) and isinstance(result.get(key),dict): result[key]=merge(result[key],value)
        else: result[key]=value
    return result
