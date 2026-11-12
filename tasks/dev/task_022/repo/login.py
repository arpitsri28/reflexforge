def login(codes, code, now):
    return {'session_user': codes.redeem(code, now)}
