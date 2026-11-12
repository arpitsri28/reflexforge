from headers import bearer
def credentials(headers): return bearer(headers['Authorization'])
