from policy import can_edit
assert not can_edit({'org': 'a', 'id': 1, 'admin': True}, {'org': 'b', 'owner': 2})
