import asyncio
import base64
import json
import time

import httpx

from .supermarket import SupermarketConnector


class NewWorldConnector(SupermarketConnector):
    BASE_WEB_URL = "https://www.newworld.co.nz"
    BASE_API_URL = "https://api-prod.newworld.co.nz/v1/edge"

    STORES_URL = f"{BASE_API_URL}/store"
    PRODUCTS_URL = f"{BASE_API_URL}/search/paginated/products"

    TOKEN_EXPIRY_MARGIN = 30
    MAX_CONCURRENT_SEARCHES = 5

    # Passive in-memory store cache.
    # This does NOT create a timer or background task.
    # The age is checked only when get_stores() is called.
    STORE_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )

    def __init__(self):
        # Guest-token cache.
        self.token: str | None = None
        self.token_expires_at = 0.0

        # Prevent several simultaneous requests from all refreshing
        # the token at the same time.
        self._token_lock = asyncio.Lock()

        # Store-list cache for the lifetime of this Python process.
        self._stores: list[dict] = []
        self._stores_cached_at: float | None = None

        # Prevent simultaneous requests from all fetching the full
        # New World store list at once when the cache is empty/expired.
        self._stores_lock = asyncio.Lock()

    # ---------------------------------------------------------
    # HTTP HELPERS
    # ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": self.BASE_WEB_URL,
            "Referer": f"{self.BASE_WEB_URL}/",
        }

    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._headers(),
            timeout=20.0,
            follow_redirects=True,
        )

    # ---------------------------------------------------------
    # PRODUCT SEARCH
    # ---------------------------------------------------------

    async def search_products(
        self,
        queries: str | list[str],
        store_id: str,
        limit: int = 48,
        page: int = 1,
    ) -> dict[str, list]:
        if not store_id:
            raise ValueError("store_id is required")

        store_id = str(store_id)

        if not 1 <= limit <= 48:
            raise ValueError("limit must be between 1 and 48")

        if page < 1:
            raise ValueError("page must be at least 1")

        # Always work internally with a list.
        if isinstance(queries, str):
            queries = [queries]

        # Strip empty queries and remove duplicates while
        # preserving the original order.
        queries = list(
            dict.fromkeys(
                query.strip()
                for query in queries
                if isinstance(query, str) and query.strip()
            )
        )

        if not queries:
            return {}

        async with self._create_client() as client:
            # Called once for the entire batch.
            # This reuses the cached guest token while valid.
            token = await self.get_guest_token(client)

            semaphore = asyncio.Semaphore(
                self.MAX_CONCURRENT_SEARCHES
            )

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

    async def _search_one(
        self,
        client: httpx.AsyncClient,
        token: str,
        query: str,
        store_id: str,
        limit: int,
        page: int,
    ) -> list:
        page_index = page - 1

        payload = {
            "algoliaQuery": {
                "attributesToHighlight": [],
                "attributesToRetrieve": [
                    "productID",
                    "Type",
                    "sponsored",
                    "category0NI",
                    "category1NI",
                    "category2NI",
                ],
                "facets": [
                    "brand",
                    "category1NI",
                    "onPromotion",
                    "productFacets",
                    "tobacco",
                ],

                # This is what scopes the New World search to
                # the single selected store.
                "filters": f"stores:{store_id}",

                "highlightPostTag": "__/ais-highlight__",
                "highlightPreTag": "__ais-highlight__",
                "hitsPerPage": limit,
                "maxValuesPerFacet": 100,
                "page": page_index,
                "query": query,
                "analyticsTags": [
                    "fs#WEB:desktop",
                ],
            },
            "algoliaFacetQueries": [],
            "storeId": store_id,
            "hitsPerPage": limit,
            "page": page_index,
            "sortOrder": "NI_POPULARITY_ASC",
            "tobaccoQuery": True,
            "precisionMedia": {
                "adDomain": "SEARCH_PAGE",
                "adPositions": [4, 8, 12],
                "publishImpressionEvent": False,
                "disableAds": False,
            },
        }

        response = await client.post(
            self.PRODUCTS_URL,
            headers={
                "Authorization": f"Bearer {token}",
            },
            json=payload,
        )

        response.raise_for_status()

        data = response.json()

        products = data.get("products", [])

        if not isinstance(products, list):
            raise RuntimeError(
                "Unexpected New World product response: "
                "'products' was not a list"
            )

        return products

    # ---------------------------------------------------------
    # GUEST TOKEN
    # ---------------------------------------------------------

    def get_token_expiry(
        self,
        token: str,
    ) -> float | None:
        try:
            payload = token.split(".")[1]

            # Add missing Base64 padding.
            payload += "=" * (-len(payload) % 4)

            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)

            expiry = data.get("exp")

            if expiry is None:
                return None

            return float(expiry)

        except Exception:
            return None

    def _token_is_valid(self) -> bool:
        return bool(
            self.token
            and time.time() < self.token_expires_at
        )

    async def get_guest_token(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        # Fast path: reuse a valid cached token.
        if self._token_is_valid():
            return self.token  # type: ignore[return-value]

        async with self._token_lock:
            # Another request may have refreshed the token while
            # this request was waiting for the lock.
            if self._token_is_valid():
                return self.token  # type: ignore[return-value]

            response = await client.post(
                f"{self.BASE_WEB_URL}/api/user/get-current-user",
                json={
                    "fingerprintUser": "agora",
                    "fingerprintGuest": self.USER_AGENT,
                },
            )

            response.raise_for_status()

            data = response.json()

            access_token = data["access_token"]

            expiry = self.get_token_expiry(access_token)

            if expiry:
                self.token = access_token
                self.token_expires_at = (
                    expiry - self.TOKEN_EXPIRY_MARGIN
                )

            elif "expires_in" in data:
                self.token = access_token
                self.token_expires_at = (
                    time.time()
                    + int(data["expires_in"])
                    - self.TOKEN_EXPIRY_MARGIN
                )

            else:
                # No reliable expiry information:
                # don't cache the token.
                self.token = None
                self.token_expires_at = 0.0

            return access_token

    # ---------------------------------------------------------
    # STORE CACHE
    # ---------------------------------------------------------

    def _store_cache_is_fresh(self) -> bool:
        if not self._stores or self._stores_cached_at is None:
            return False

        age = time.monotonic() - self._stores_cached_at

        return age < self.STORE_CACHE_TTL_SECONDS

    async def _fetch_stores(self) -> list[dict]:
        """
        Fetch the current New World store list from New World.

        This method always goes to New World. Cache decisions are
        handled by get_stores().
        """
        async with self._create_client() as client:
            token = await self.get_guest_token(client)

            response = await client.get(
                self.STORES_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                },
            )

            response.raise_for_status()

            data = response.json()

        stores = data.get("stores", [])

        if not isinstance(stores, list):
            raise RuntimeError(
                "Unexpected New World store response: "
                "'stores' was not a list"
            )

        return stores

    async def get_stores(
        self,
        force_refresh: bool = False,
    ) -> list[dict]:
        """
        Return the New World store list.

        Cache behaviour:
        - Fresh cache: return immediately, no New World request.
        - Missing/expired cache: fetch once and cache for 6 hours.
        - force_refresh=True: bypass the cache and fetch immediately.

        This is a passive TTL cache. It does not schedule anything,
        create a background task, or keep a sleeping Render service awake.
        """
        if not force_refresh and self._store_cache_is_fresh():
            return list(self._stores)

        async with self._stores_lock:
            # Another request may have refreshed the stores while
            # this request was waiting for the lock.
            if not force_refresh and self._store_cache_is_fresh():
                return list(self._stores)

            stores = await self._fetch_stores()

            self._stores = stores
            self._stores_cached_at = time.monotonic()

            return list(self._stores)
