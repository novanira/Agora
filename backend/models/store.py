class Store:
    def __init__(
            self,
            supermarket: str,
            name: str,
            id: str,
            latitude: float,
            longitude: float,
            address: str
        ):
        self.supermarket = supermarket
        self.name = name
        self.id = id
        self.latitude = latitude
        self.longitude = longitude
