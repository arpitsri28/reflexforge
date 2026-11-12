def add_cart(stock, cart, count):
    stock.reserve(cart, count)
    return stock.available()
