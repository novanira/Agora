from abc import ABC, abstractmethod


class SupermarketConnector(ABC):

    @abstractmethod
    async def get_stores(self) -> list:
        pass

    @abstractmethod
    async def search_products(
        self,
        queries: str | list[str],
        store_id: str,
        limit: int = 48,
        page: int = 1,
    ) -> dict[str, list]:
        pass
