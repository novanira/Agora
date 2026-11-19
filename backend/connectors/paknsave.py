import asyncio
import base64
import json
import math
import time
from urllib.parse import urljoin

import httpx

from models.product import Product
from .new_world import NewWorldConnector
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
    ) -> list[object]:
        response = await client.post(
            f"{self.BASE_API_URL}/search/paginated/products",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "algoliaQuery": {
                    "attributesToHighlight": [],
                    "attributesToRetrieve": ["productID", "Type", "sponsored", "categoryTrees"],
                    "facets": ["brand", "category1NI", "onPromotion", "productFacets", "tobacco"],
                    "filters": f"stores:{store_id}",
                    "highlightPostTag": "__/ais-highlight__",
                    "highlightPreTag": "__ais-highlight__",
                    "hitsPerPage": limit,
                    "maxValuesPerFacet": 100,
                    "page": page_index,
                    "query": query,
                    "analyticsTags": ["fs#WEB:desktop"],
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
            },
        )
        response.raise_for_status()

        data = response.json()
        products = data.get("products", []) if isinstance(data, dict) else None
        if not isinstance(products, list):
            raise RuntimeError("Unexpected Pak'nSave product response: 'products' was not a list")
        return products

    async def _search_one(
        self,
        client: httpx.AsyncClient,
        token: str,
        query: str,
        store_id: str,
        limit: int,
        page: int,
        pages: int | None = None,
    ) -> list[Product]:
        products: list[Product] = []
        seen_ids: set[str] = set()
        first_index = page - 1
        end_index = first_index + pages if pages is not None else None

        async def fetch(page_index: int) -> list[object]:
            return await self._fetch_product_page(
                client=client,
                token=token,
                query=query,
                store_id=store_id,
                limit=limit,
                page_index=page_index,
            )

        def collect(rows: list[object]) -> None:
            for raw_product in rows:
                if not isinstance(raw_product, dict):
                    continue
                product = self._to_product(raw_product, store_id)
                if product is None:
                    continue
                product_id = str(product.product_id)
                if product_id in seen_ids:
                    continue
                seen_ids.add(product_id)
                products.append(product)

        first_page = await fetch(first_index)
        collect(first_page)
        if len(first_page) < limit:
            return products

        next_index = first_index + 1
        while end_index is None or next_index < end_index:
            batch_end = next_index + self.MAX_CONCURRENT_PAGES
            if end_index is not None:
                batch_end = min(batch_end, end_index)
            results = await asyncio.gather(
                *(fetch(index) for index in range(next_index, batch_end)),
                return_exceptions=True,
            )
            # Ignore speculative requests after an earlier page has exhausted the results.
            for rows in results:
                if isinstance(rows, BaseException):
                    raise rows
                collect(rows)
                if len(rows) < limit:
                    return products
            next_index = batch_end

        return products

    def _to_product(self, raw_product: dict, store_id: str) -> Product | None:
        product_id = (
            raw_product.get("productID") or raw_product.get("productId") or raw_product.get("id")
        )
        name = (
            raw_product.get("name") or raw_product.get("productName") or raw_product.get("displayName")
        )
        if product_id in (None, "") or not isinstance(name, str) or not name.strip():
            return None

        product_id = str(product_id)
        name = name.strip()
        brand = raw_product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        brand = (str(brand).strip() or None) if brand is not None else None
        if brand and not name.lower().startswith(brand.lower()):
            name = f"{brand} {name}"

        price = NewWorldConnector._get_price(raw_product)
        if price is not None and (not math.isfinite(price) or price < 0):
            price = None
        original_price = NewWorldConnector._get_original_price(raw_product)
        if (
            price is None or original_price is None
            or not math.isfinite(original_price) or original_price <= price
        ):
            original_price = None

        amount, quantity, unit = NewWorldConnector._get_amount_quantity_and_unit(raw_product, product_id)
        image = NewWorldConnector._get_image_url(raw_product, product_id)
        url = raw_product.get("productUrl") or raw_product.get("url")
        if not isinstance(url, str) or not url.strip():
            url = f"/shop/product/{product_id.lower()}"

        return Product(
            supermarket="PAK'nSAVE",
            store_id=str(store_id),
            product_id=product_id,
            name=name,
            price=price if price is not None else 0.0,
            promotion=NewWorldConnector._get_promotion(raw_product),
            brand=brand,
            category_levels=NewWorldConnector._get_category_levels(raw_product),
            original_price=original_price,
            amount=amount,
            quantity=quantity,
            unit=unit,
            barcode=raw_product.get("barcode") or raw_product.get("gtin"),
            image_url=urljoin(self.BASE_WEB_URL, image) if image else None,
            product_url=urljoin(self.BASE_WEB_URL, url),
            available=price is not None and NewWorldConnector._is_available(raw_product),
        )

    async def search_products(
        self,
        queries: str | list[str],
        store_id: str,
        limit: int = 48,
        page: int = 1,
        pages: int | None = None,
    ) -> dict:
        if not store_id:
            raise ValueError("store_id is required")
        store_id = str(store_id)
        if not 1 <= limit <= 48:
            raise ValueError("limit must be between 1 and 48")
        if page < 1:
            raise ValueError("page must be at least 1")
        if pages is not None and (type(pages) is not int or pages < 1):
            raise ValueError("pages must be None or a positive integer")
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
                        pages=pages,
                    )

                    return query, products

            results = await asyncio.gather(
                *(search(query) for query in queries)
            )

        return dict(results)
