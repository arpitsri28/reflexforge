from app import create
assert create().resolve('/users/me') == 'self'
