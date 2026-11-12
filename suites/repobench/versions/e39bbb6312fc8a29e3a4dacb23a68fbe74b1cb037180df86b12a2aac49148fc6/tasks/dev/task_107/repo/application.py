from repository import Repository
from authentication import Authentication
from policy import Policy
from cache import Decisions
from service import Documents
from middleware import Middleware
def build(principals,documents,tokens):
    repository=Repository(principals,documents);policy=Policy()
    return repository,policy,Middleware(Authentication(repository,tokens),Documents(repository,Decisions(),policy))
