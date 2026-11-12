from policy import can_edit
def authorize(user, doc):
    if not can_edit(user, doc): raise PermissionError('denied')
    return doc['id']
