from .new_world import NewWorldConnector
from .woolworths import WoolworthsConnector


connectors = {
    "new_world": NewWorldConnector(),
    "woolworths": WoolworthsConnector(),
}