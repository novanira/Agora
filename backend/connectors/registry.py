from .new_world import NewWorldConnector
from .woolworths import WoolworthsConnector
from .paknsave import PakNSaveConnector


connectors = {
    "new_world": NewWorldConnector(),
    "woolworths": WoolworthsConnector(),
    "paknsave": PakNSaveConnector()
}
