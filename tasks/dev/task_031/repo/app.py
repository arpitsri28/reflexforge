from routing import Router
def create():
    r = Router()
    r.add('/users/:id', 'user')
    r.add('/users/me', 'self')
    return r
