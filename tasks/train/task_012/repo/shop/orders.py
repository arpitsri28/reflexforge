from prices import PRICES
def total(lines):
    return sum(PRICES[name] * count for name, count in lines)
