def collect(fetch):
    cursor, seen, result = None, set(), []
    while True:
        page = fetch(cursor)
        result.extend(page['items'])
        cursor = page['next_cursor']
        if not page['items']: break
        if cursor in seen: raise ValueError('cursor cycle')
        seen.add(cursor)
    return result
