import asyncio
import base64
import json
import time

import httpx

from models.product import Product
from .supermarket import SupermarketConnector

class PakNSaveConnector(SupermarketConnector):
    BASE_WEB_URL = "https://www.paknsave.co.nz"
    BASE_API_URL = "https://api-prod.paknsave.co.nz/v1/edge"

    TOKEN_EXPIRY_MARGIN = 30
    STORE_CACHE_TTL_SECONDS = 6 * 60 * 60

    MAX_CONCURRENT_SEARCHES = 6
    MAX_CONCURRENT_PAGES = 3

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
    
    def __init__(self):
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

        self._stores: list = []
        self._stores_cached_at: float | None = None
        self._stores_lock = asyncio.Lock()


    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Origin": self.BASE_WEB_URL,
                "Referer": f"{self.BASE_WEB_URL}/",
            },
            timeout=20.0,
            limits=httpx.Limits(
                max_connections=18,
                max_keepalive_connections=12,
                keepalive_expiry=30.0,
            ),
            follow_redirects=True,
        )

    def _is_token_valid(self) -> bool:
        if self._token and time.time() < self._token_expires_at:
            return True
        return False

    @staticmethod
    def _get_token_expiry(token: str) -> float | None:
        try:
            raw_payload = token.split(".")[1]
            payload_dict = json.loads(base64.urlsafe_b64decode(raw_payload + (((4 - len(raw_payload) % 4) % 4) * "=")))
            expiry = payload_dict.get("exp")

            return float(expiry) if expiry is not None else None

        except Exception:
            return None

    async def get_guest_token(self, client: httpx.AsyncClient) -> str:
        if self._is_token_valid():
            assert self._token is not None
            return self._token

        async with self._token_lock:
            if self._is_token_valid():
                assert self._token is not None
                return self._token

            response = await client.post(
                f"{self.BASE_WEB_URL}/api/user/get-current-user",
                json={
                    "fingerprintUser": "agora",
                    "fingerprintGuest": self.USER_AGENT,
                }
            )

            response.raise_for_status()

            token = response.json()["access_token"]

            expiry = self._get_token_expiry(token)
            if expiry is not None:
                self._token = token
                self._token_expires_at = expiry - self.TOKEN_EXPIRY_MARGIN

            return token

    def _is_store_cache_fresh(self) -> bool:
        if not self._stores or self._stores_cached_at is None:
            return False
        age = time.monotonic() - self._stores_cached_at
        return age < self.STORE_CACHE_TTL_SECONDS
        

    async def _fetch_stores(self):
        async with self._create_client() as client:
            token = await self.get_guest_token(client)

            response = await client.get(
                f"{self.BASE_API_URL}/store", 
                headers={"Authorization": f"Bearer {token}"}
            )

            response.raise_for_status()

            return response.json().get("stores", [])

    async def get_stores(self, force_refresh: bool = False) -> list:
        if not force_refresh and self._is_store_cache_fresh():
            print('from store cache')
            return list(self._stores)

        async with self._stores_lock:
            if not force_refresh and self._is_store_cache_fresh():
                return list(self._stores)

            stores = await self._fetch_stores()

            self._stores = stores
            self._stores_cached_at = time.monotonic()

            print('caching stores')

            return list(self._stores)

    async def _fetch_product_page(
        self,
        client: httpx.AsyncClient,
        token: str,
        query: str,
        store_id: str,
        limit: int,
        page_index: int,
    ) -> list[dict]:
        pass

    async def _search_one(
        self,
        client: httpx.AsyncClient,
        token: str,
        query: str,
        store_id: str,
        limit: int,
        page: int,
    ) -> list:
        pass

    async def search_products(
        self,
        queries: str | list[str],
        store_id: str,
        limit: int = 48,
        page: int = 1
    ) -> dict:
        if not store_id:
            raise ValueError("store_id is required")
        store_id = str(store_id)
        if not 1 <= limit <= 48:
            raise ValueError("limit must be between 1 and 48")
        if page < 1:
            raise ValueError("page must be at least 1")
        if isinstance(queries, str):
            queries = [queries]
        queries = list(dict.fromkeys(query.strip() for query in queries if isinstance(query, str) and query.strip()))
        if not queries:
            return {}

        async with self._create_client() as client:
            token = await self.get_guest_token(client)
            semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SEARCHES)
            async def search(query: str):
                async with semaphore:
                    products = await self._search_one(
                        client=client,
                        token=token,
                        query=query,
                        store_id=store_id,
                        limit=limit,
                        page=page,
                    )

                    return query, products

            results = await asyncio.gather(
                *(search(query) for query in queries)
            )

        return dict(results)
