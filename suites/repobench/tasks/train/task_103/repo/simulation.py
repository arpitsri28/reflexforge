def drain(consumer):
    outcomes=[]
    while consumer.broker.pending: outcomes.append(consumer.once())
    return outcomes
