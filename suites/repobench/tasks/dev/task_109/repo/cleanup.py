def release(resources):
    for resource in reversed(resources): resource.close()
    return []
