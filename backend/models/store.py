from pydantic import BaseModel


class Store(BaseModel):
    id: str
    chain: str
    name: str

    address: str | None = None
    suburb: str | None = None
    city: str | None = None

    latitude: float | None = None
    longitude: float | None = None