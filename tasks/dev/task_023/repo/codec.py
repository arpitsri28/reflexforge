def encode(rows):
    return '\n'.join(','.join(row) for row in rows)
def decode(text):
    return [line.split(',') for line in text.splitlines()]
