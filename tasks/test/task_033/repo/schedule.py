from intervals import coalesce
def occupied(intervals): return sum(b - a for a, b in coalesce(intervals))
