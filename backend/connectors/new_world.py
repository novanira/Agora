import asyncio
import base64
import json
import re
import time

import httpx

from models.product import Product
from .supermarket import SupermarketConnector


class NewWorldConnector(SupermarketConnector):
    BASE_WEB_URL = "https://www.newworld.co.nz"
    BASE_API_URL = "https://api-prod.newworld.co.nz/v1/edge"

    STORES_URL = f"{BASE_API_URL}/store"
    PRODUCTS_URL = f"{BASE_API_URL}/search/paginated/products"

    TOKEN_EXPIRY_MARGIN = 30
    # Balanced for Render + New World's API: higher values showed diminishing returns.
    MAX_CONCURRENT_SEARCHES = 6
    MAX_CONCURRENT_PAGES = 3

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
            limits=httpx.Limits(
                max_connections=18,
                max_keepalive_connections=12,
                keepalive_expiry=30.0,
            ),
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
    ) -> list[Product]:
        """Fetch all pages for one query and return unique Product objects."""
        all_products: list[Product] = []
        seen_product_ids: set[str] = set()
        start_page_index = page - 1

        def add_products(raw_products: list[dict]) -> None:
            for raw_product in raw_products:
                product = self._to_product(raw_product, store_id)
                if product is None:
                    continue

                product_id = str(product.product_id)
                if product_id in seen_product_ids:
                    continue

                seen_product_ids.add(product_id)
                all_products.append(product)

        first_page = await self._fetch_product_page(
            client=client,
            token=token,
            query=query,
            store_id=store_id,
            limit=limit,
            page_index=start_page_index,
        )

        add_products(first_page)

        if len(first_page) < limit:
            return all_products

        next_page_index = start_page_index + 1

        while True:
            page_indexes = list(
                range(
                    next_page_index,
                    next_page_index + self.MAX_CONCURRENT_PAGES,
                )
            )

            page_results = await asyncio.gather(
                *(
                    self._fetch_product_page(
                        client=client,
                        token=token,
                        query=query,
                        store_id=store_id,
                        limit=limit,
                        page_index=page_index,
                    )
                    for page_index in page_indexes
                )
            )

            reached_last_page = False

            for raw_products in page_results:
                if reached_last_page:
                    break

                add_products(raw_products)

                if len(raw_products) < limit:
                    reached_last_page = True

            if reached_last_page:
                break

            next_page_index += self.MAX_CONCURRENT_PAGES

        return all_products

    async def _fetch_product_page(
        self,
        client: httpx.AsyncClient,
        token: str,
        query: str,
        store_id: str,
        limit: int,
        page_index: int,
    ) -> list[dict]:
        """Fetch one New World product-search page."""
        payload = {
            "algoliaQuery": {
                "attributesToHighlight": [],
                "attributesToRetrieve": [
                    "productID",
                    "Type",
                    "sponsored",
                    "categoryTrees",
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
        products = data.get("products", [])

        if not isinstance(products, list):
            raise RuntimeError(
                "Unexpected New World product response: "
                "'products' was not a list"
            )

        return [
            product
            for product in products
            if isinstance(product, dict)
        ]




    def _to_product(
        self,
        raw_product: dict,
        store_id: str,
    ) -> Product | None:
        
        print(raw_product)

        """Convert one New World result into the shared Product model."""
        product_id = (
            raw_product.get("productID")
            or raw_product.get("productId")
            or raw_product.get("id")
        )

        name = (
            raw_product.get("name")
            or raw_product.get("productName")
            or raw_product.get("displayName")
        )

        if (
            product_id in (None, "")
            or not isinstance(name, str)
            or not name.strip()
        ):
            return None

        price = self._get_price(raw_product)
        if price is None:
            price = 0.0

        promotion = self._get_promotion(raw_product)

        original_price = self._get_original_price(raw_product)
        if original_price is not None and original_price <= price:
            original_price = None

        brand = raw_product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")

        if brand is not None:
            brand = str(brand).strip() or None

        name = name.strip()

        if brand and not name.lower().startswith(brand.lower()):
            name = f"{brand} {name}"

        amount, quantity, unit = self._get_amount_quantity_and_unit(
            raw_product,
            str(product_id),
        )

        category_levels = self._get_category_levels(raw_product)

        return Product(
            supermarket="New World",
            store_id=str(store_id),
            product_id=str(product_id),
            name=name,
            price=price,
            promotion=promotion,
            brand=brand,
            category_levels=category_levels,
            original_price=original_price,
            amount=amount,
            quantity=quantity,
            unit=unit,
            barcode=raw_product.get("barcode") or raw_product.get("gtin"),
            image_url=self._get_image_url(raw_product, str(product_id)),
            product_url=(
                raw_product.get("productUrl")
                or raw_product.get("url")
                or f"{self.BASE_WEB_URL}/shop/product/{str(product_id).lower()}"
            ),
            available=self._is_available(raw_product),
        )




    @staticmethod
    def _get_category_levels(
        raw_product: dict,
    ) -> dict[str, list[str]]:
        """
        Extract every New World category path from `categoryTrees`.

        New World's categoryTrees start directly at the department, while
        Woolworths includes "All Departments" above the department level.
        To keep Agora's category hierarchy consistent across supermarkets:

            Agora level_0 = All Departments
            Agora level_1 = New World categoryTrees.level0
            Agora level_2 = New World categoryTrees.level1
            Agora level_3 = New World categoryTrees.level2

        Products can belong to multiple category trees, so values are
        collected and deduplicated independently at each level.
        """
        category_levels = {
            "level_0": ["All Departments"],
            "level_1": [],
            "level_2": [],
            "level_3": [],
        }

        trees = raw_product.get("categoryTrees")
        if not isinstance(trees, list):
            return category_levels

        seen = {
            "level_1": set(),
            "level_2": set(),
            "level_3": set(),
        }

        for tree in trees:
            if not isinstance(tree, dict):
                continue

            # Shift New World's hierarchy down one level so it matches
            # Woolworths' "All Departments" root level.
            for source_index in range(3):
                value = tree.get(f"level{source_index}")
                if not isinstance(value, str):
                    continue

                value = value.strip()
                if not value:
                    continue

                target_key = f"level_{source_index + 1}"

                if value in seen[target_key]:
                    continue

                seen[target_key].add(value)
                category_levels[target_key].append(value)

        return category_levels

    @classmethod
    def _get_amount_quantity_and_unit(
        cls,
        raw_product: dict,
        product_id: str | None = None,
    ) -> tuple[float | None, float | None, str | None]:
        """
        Extract multipack count plus the size of each item.

        Example:
            6 x 330ml -> amount=6, quantity=330, unit="ml"
            500ml     -> amount=None, quantity=500, unit="ml"
        """
        # New World encodes the selling unit in many product IDs.
        # Example: 5039945-KGM-000 = sold by kilogram.
        #
        # This is more authoritative than trying to infer a size from the
        # product name. A loose apple may have no "1kg" text in its name, but
        # its price is still a per-kilogram price.
        if product_id:
            product_id_parts = str(product_id).upper().split("-")
            if len(product_id_parts) >= 2 and product_id_parts[1] == "KGM":
                return None, 1.0, "kg"

        texts = [
            raw_product.get("size"),
            raw_product.get("packSize"),
            raw_product.get("displayName"),
            raw_product.get("name"),
            raw_product.get("productName"),
        ]

        texts = [
            value.strip()
            for value in texts
            if isinstance(value, str) and value.strip()
        ]

        multipack_pattern = re.compile(
            r"\b(\d+)\s*[x×]\s*"
            r"(\d+(?:\.\d+)?)\s*"
            r"(ml|l|g|kg|mg)\b",
            flags=re.IGNORECASE,
        )

        for text in texts:
            match = multipack_pattern.search(text)
            if match:
                return (
                    float(match.group(1)),
                    float(match.group(2)),
                    match.group(3).lower(),
                )

        pack_with_size_pattern = re.compile(
            r"\b(\d+)\s*(?:pack|pk)\b"
            r".*?"
            r"(\d+(?:\.\d+)?)\s*"
            r"(ml|l|g|kg|mg)\b",
            flags=re.IGNORECASE,
        )

        for text in texts:
            match = pack_with_size_pattern.search(text)
            if match:
                return (
                    float(match.group(1)),
                    float(match.group(2)),
                    match.group(3).lower(),
                )

        pack_pattern = re.compile(
            r"\b(\d+)\s*(?:pack|pk)\b",
            flags=re.IGNORECASE,
        )

        amount = None
        for text in texts:
            match = pack_pattern.search(text)
            if match:
                amount = float(match.group(1))
                break

        # Prefer explicit quantity/unit fields if New World supplied them.
        quantity = cls._to_float(raw_product.get("quantity"))
        unit = raw_product.get("unit") or raw_product.get("unitOfMeasure")

        if quantity is not None and unit:
            return amount, quantity, str(unit).strip().lower()

        size_pattern = re.compile(
            r"(?i)(\d+(?:\.\d+)?)\s*(ml|l|g|kg|mg)\b"
        )

        for text in texts:
            matches = list(size_pattern.finditer(text))
            if matches:
                match = matches[-1]
                return amount, float(match.group(1)), match.group(2).lower()

        return amount, quantity, str(unit).strip().lower() if unit else None

    @staticmethod
    def _get_image_url(
        raw_product: dict,
        product_id: str,
    ) -> str | None:
        """Return New World's product image URL."""
        for key in ("imageUrl", "imageURL", "image", "imageUri"):
            value = raw_product.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        images = raw_product.get("images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                for key in ("url", "imageUrl", "src"):
                    value = first.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

        # Foodstuffs' public product-image CDN uses the numeric product code.
        # This also covers search responses that omit an explicit image field.
        numeric_id = product_id.split("-", 1)[0]
        if numeric_id.isdigit():
            return (
                "https://a.fsimg.co.nz/product/retail/fan/image/400x400/"
                f"{numeric_id}.png?w=640"
            )

        return None

    @classmethod
    def _get_promotion(cls, raw_product: dict) -> dict | None:
        promotions = raw_product.get("promotions")

        if not isinstance(promotions, list) or not promotions:
            return None

        promo = next(
            (
                p for p in promotions
                if isinstance(p, dict) and p.get("bestPromotion")
            ),
            None,
        )

        if promo is None:
            return None

        reward_value = cls._to_float(
            promo.get("rewardValue")
        )

        threshold = cls._to_float(
            promo.get("threshold")
        )

        comparative_price = promo.get("comparativePrice", {})

        unit_price = None
        if isinstance(comparative_price, dict):
            unit_price = cls._to_float(
                comparative_price.get("pricePerUnit")
            )

        if reward_value is None:
            return None

        return {
            "type": (
                "MULTIBUY"
                if threshold and threshold > 1
                else "DISCOUNT"
            ),
            "quantity": int(threshold) if threshold else 1,
            "total_price": reward_value / 100,
            "requires_membership": promo.get(
                "cardDependencyFlag",
                False,
            ),
        }

    @classmethod
    def _get_price(cls, raw_product: dict) -> float | None:
        single_price = raw_product.get("singlePrice")

        if isinstance(single_price, dict):
            price = cls._to_float(single_price.get("price"))
            if price is not None:
                return price / 100

        price = cls._to_float(raw_product.get("averagePrice"))
        if price is not None:
            return price

        return cls._to_float(raw_product.get("price"))

    @classmethod
    def _get_original_price(cls, raw_product: dict) -> float | None:
        single_price = raw_product.get("singlePrice")

        if isinstance(single_price, dict):
            for key in ("wasPrice", "originalPrice"):
                price = cls._to_float(single_price.get(key))
                if price is not None:
                    return price / 100

        for key in ("wasPrice", "originalPrice"):
            price = cls._to_float(raw_product.get(key))
            if price is not None:
                return price

        return None

    @staticmethod
    def _is_available(raw_product: dict) -> bool:
        # Prefer New World's explicit boolean fields when present.
        for key in ("isAvailable", "available", "inStock"):
            value = raw_product.get(key)
            if isinstance(value, bool):
                return value

        status = (
            raw_product.get("availabilityStatus")
            or raw_product.get("stockStatus")
        )

        if status is not None:
            normalised = "".join(
                char for char in str(status).lower()
                if char.isalnum()
            )

            if normalised in {
                "outofstock",
                "unavailable",
                "notavailable",
                "soldout",
            }:
                return False

            if normalised in {
                "instock",
                "available",
                "lowstock",
                "limitedstock",
            }:
                return True

            # A status was supplied but we do not recognise it.
            return False

        # The search endpoint normally returns purchasable store products.
        # If it supplies no stock field at all, preserve the original behaviour.
        return True

    @staticmethod
    def _to_float(value) -> float | None:
        if value in (None, "", "null"):
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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
