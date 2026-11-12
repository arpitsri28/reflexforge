def fetch(cache, key, loader):
    try: return cache.get(key)
    except KeyError:
        value = loader(key)
        cache.put(key, value)
        return value
