def pay(service, request):
    return service.submit(request['key'], request['amount'])
