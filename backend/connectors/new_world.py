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

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self.token = None
        self.token_expires_at = 0

    async def search_products(
        self,
        queries: str | list[str],
        store_id: str,
        limit: int = 48,
        page: int = 1,
    ) -> dict[str, list]:
        if not store_id:
            raise ValueError("store_id is required")

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
                if query.strip()
            )
        )

        if not queries:
            return {}

        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": self.BASE_WEB_URL,
            "Referer": f"{self.BASE_WEB_URL}/",
        }

        async with httpx.AsyncClient(
            headers=headers,
            timeout=20.0,
        ) as client:
            # Called once for the entire batch.
            # This will reuse the cached token if valid.
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

        return data.get("products", [])

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

            return data.get("exp")

        except Exception:
            return None

    async def get_guest_token(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        # Reuse cached token while it remains valid.
        if (
            self.token
            and time.time() < self.token_expires_at
        ):
            return self.token

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
            self.token_expires_at = 0

        return access_token

    async def get_stores(self) -> list:
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": self.BASE_WEB_URL,
            "Referer": f"{self.BASE_WEB_URL}/",
        }

        async with httpx.AsyncClient(
            headers=headers,
            timeout=20.0,
        ) as client:
            token = await self.get_guest_token(client)

            response = await client.get(
                self.STORES_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                },
            )

            response.raise_for_status()

            data = response.json()

            return data.get("stores", [])