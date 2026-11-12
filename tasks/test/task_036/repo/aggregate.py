from stats import partition
def mean(partitions):
    summaries = [partition(rows) for rows in partitions]
    means = [total / weight for total, weight in summaries if weight]
    return sum(means) / len(means) if means else None
