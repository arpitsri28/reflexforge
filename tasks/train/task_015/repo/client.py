from pages import collect
def values(fetch): return [row['value'] for row in collect(fetch)]
