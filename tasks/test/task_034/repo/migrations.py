def canonical(fields, version):
    if version == 1: return {'name': fields['full_name']}
    return {'name': fields['first'] + ' ' + fields['last']}
