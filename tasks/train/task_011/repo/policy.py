def can_edit(user, doc):
    return user['org'] == doc['org'] and user['id'] == doc['owner'] or user['admin']
