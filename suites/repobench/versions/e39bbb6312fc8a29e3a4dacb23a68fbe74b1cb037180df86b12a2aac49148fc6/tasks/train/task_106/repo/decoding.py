def decode(page):
    if not isinstance(page.get('items'),list) or 'next' not in page: raise ValueError('page schema')
    rows=[]
    for row in page['items']:
        if not isinstance(row.get('id'),str) or type(row.get('price')) is not int: raise ValueError('product schema')
        rows.append(dict(row))
    return rows
