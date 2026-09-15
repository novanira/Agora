from abc import ABC, abstractmethod


class SupermarketConnector(ABC):

    @abstractmethod
    async def search_products(self, query: str) -> list:
        pass