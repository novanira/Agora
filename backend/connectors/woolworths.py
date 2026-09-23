import asyncio
import re
import time

import httpx

from models.product import Product
from .supermarket import SupermarketConnector


# Reuse these patterns and aliases for every product in a search.
_AVAILABILITY_PATTERN = re.compile(r"[^a-z0-9]+")
_UNIT_PATTERN = re.compile(r"[^a-z]")
_MULTIPACK_PATTERN = re.compile(
    r"\b(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(kg|g|mg|l|ml)\b",
    re.IGNORECASE,
)
_PACK_WITH_SIZE_PATTERN = re.compile(
    r"\b(\d+)\s*(?:pack|pk)\b.*?(\d+(?:\.\d+)?)\s*(kg|g|mg|l|ml)\b",
    re.IGNORECASE,
)
_PACK_PATTERN = re.compile(r"\b(\d+)\s*(?:pack|pk)\b", re.IGNORECASE)
_SIZE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*(kg|g|mg|l|ml)\b",
    re.IGNORECASE,
)
_UNIT_ALIASES = {
    "kilogram": "kg",
    "kilograms": "kg",
    "kgs": "kg",
    "gram": "g",
    "grams": "g",
    "litre": "l",
    "litres": "l",
    "liter": "l",
    "liters": "l",
    "millilitre": "ml",
    "millilitres": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "ea": "each",
    "each": "each",
    "pk": "pack",
    "pack": "pack",
}


def _normalise_unit(value) -> str | None:
    if value in (None, ""):
        return None

    unit = _UNIT_PATTERN.sub("", str(value).strip().lower())
    return _UNIT_ALIASES.get(unit, unit or None)


def _clean_category_values(value) -> list[str]:
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []

    if isinstance(value, (list, tuple)):
        result: list[str] = []
        seen: set[str] = set()

        for item in value:
            if not isinstance(item, str):
                continue

            item = item.strip()
            if not item or item in seen:
                continue

            seen.add(item)
            result.append(item)

        return result

    return []


class WoolworthsConnector(SupermarketConnector):
    BASE_URL = "https://www.woolworths.co.nz"
    GRAPHQL_URL = f"{BASE_URL}/api/graphql"

    STORE_LOCATOR_URL = (
        "https://contact.woolworths.com.au/storelocator/service/"
        "corporateinfo/country/nz/division/all/"
        "tradinghours/standard/weeks/1/json"
    )

    # Balanced for Render + Woolworths' API: higher values showed diminishing returns.
    MAX_CONCURRENT_SEARCHES = 6
    MAX_CONCURRENT_PAGES = 4

    # Passive in-memory cache. This does NOT run a timer or background task.
    # The cache is checked only when get_stores() / search_products() is called.
    STORE_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours

    MAX_ATTEMPTS = 3
    RETRY_BASE_DELAY = 0.75

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )

    SET_SHOPPING_MODE_QUERY = """
    mutation SetCartShoppingMode(
        $setCartShoppingModeInput: SetCartShoppingModeInput!
    ) {
        setCartShoppingMode(input: $setCartShoppingModeInput) {
            shoppingMode {
                pickupLocationId
            }
            validationResult {
                isValid
                failedValidations {
                    ruleName
                    message
                }
            }
        }
    }
    """

    PRODUCT_SEARCH_QUERY = """
    query ProductSearch($searchInput: CompositeSearchInput!) {
        My {
            products(searchInput: $searchInput) {
                results {
                    ... on ProductSummary {
                        sku
                        productName
                        slug
                        imageUrl
                        storeKey
                        brand
                        availabilityStatus

                        tags {
                            type
                            decisionInputs
                        }

                        categoryHierarchyNames {
                            lvl0
                            lvl1
                            lvl2
                            lvl3
                        }

                        variants {
                            name
                            unitOfMeasure

                            purchaseUnit {
                                unit
                            }

                            variantPrice {
                                isSpecial
                                isClubPrice
                                sellingUnit
                                sellingPrice
                                savedAmount
                                wasPrice
                            }
                        }
                    }

                    ... on SponsoredProduct {
                        sku
                        productName
                        slug
                        imageUrl
                        storeKey
                        brand
                        availabilityStatus

                        tags {
                            type
                            decisionInputs
                        }

                        categoryHierarchyNames {
                            lvl0
                            lvl1
                            lvl2
                            lvl3
                        }

                        variants {
                            name
                            unitOfMeasure

                            purchaseUnit {
                                unit
                            }

                            variantPrice {
                                isSpecial
                                isClubPrice
                                sellingUnit
                                sellingPrice
                                savedAmount
                                wasPrice
                            }
                        }
                    }
                }

                totalCount
                pageSize
                totalPages
            }
        }
    }
    """

    # These documents contain no string literals or comments. Compact their
    # whitespace once, keeping exactly the same GraphQL fields and operations.
    SET_SHOPPING_MODE_QUERY = " ".join(SET_SHOPPING_MODE_QUERY.split())
    PRODUCT_SEARCH_QUERY = " ".join(PRODUCT_SEARCH_QUERY.split())

    def __init__(self):
        # Cached store metadata for the lifetime of this Python process.
        self._stores_by_id: dict[str, dict] = {}
        self._stores_cached_at: float | None = None

        # Prevent multiple simultaneous requests on a fresh instance from
        # all downloading the Woolworths store list at once.
        self._stores_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=10.0,
            read=45.0,
            write=20.0,
            pool=10.0,
        )

    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": (
                    "application/graphql-response+json,"
                    "application/json;q=0.9"
                ),
                "Content-Type": "application/json",
                "Accept-Language": "en-NZ,en;q=0.9",
                "Origin": self.BASE_URL,
                "Referer": f"{self.BASE_URL}/",
            },
            timeout=self._timeout(),
            limits=httpx.Limits(
                max_connections=18,
                # Retain all existing connections between page batches.
                max_keepalive_connections=18,
                keepalive_expiry=30.0,
            ),
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # STORE CACHE
    # ------------------------------------------------------------------

    def _store_cache_is_fresh(self) -> bool:
        if not self._stores_by_id or self._stores_cached_at is None:
            return False

        age = time.monotonic() - self._stores_cached_at
        return age < self.STORE_CACHE_TTL_SECONDS

    async def _fetch_stores(self) -> list[dict]:
        """Fetch the current Woolworths NZ store list from Woolworths."""
        async with httpx.AsyncClient(
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json",
            },
            timeout=self._timeout(),
            follow_redirects=True,
        ) as client:
            response = await self._request_with_retries(
                client=client,
                method="GET",
                url=self.STORE_LOCATOR_URL,
                stage="store locator",
            )
            data = response.json()

        raw_stores = self._extract_store_list(data)
        stores: list[dict] = []

        for raw_store in raw_stores:
            if not isinstance(raw_store, dict):
                continue

            store = self._normalise_store(raw_store)
            if store is not None:
                stores.append(store)

        return stores

    async def get_stores(
        self,
        force_refresh: bool = False,
    ) -> list[dict]:
        """
        Return Woolworths stores.

        Cache behaviour:
        - Fresh cache: return immediately, no Woolworths request.
        - Missing/expired cache: fetch stores once and cache them.
        - force_refresh=True: fetch stores even if the cache is fresh.

        This is a passive TTL cache. Nothing runs in the background, so this
        method cannot keep a sleeping Render service awake by itself.
        """
        if not force_refresh and self._store_cache_is_fresh():
            return list(self._stores_by_id.values())

        async with self._stores_lock:
            # Another request may have refreshed while we waited for the lock.
            if not force_refresh and self._store_cache_is_fresh():
                return list(self._stores_by_id.values())

            stores = await self._fetch_stores()

            self._stores_by_id = {
                store["store_id"]: store
                for store in stores
            }
            self._stores_cached_at = time.monotonic()

            return stores

    async def _get_store(self, store_id: str) -> dict:
        store_id = str(store_id)

        # Uses the cache if it is fresh; refreshes only if needed.
        if not self._store_cache_is_fresh():
            await self.get_stores()

        store = self._stores_by_id.get(store_id)
        if store is not None:
            return store

        # The requested ID might belong to a newly added store while our cache
        # is still technically fresh. Refresh once before rejecting the ID.
        await self.get_stores(force_refresh=True)

        store = self._stores_by_id.get(store_id)
        if store is None:
            raise ValueError(
                f"Unknown Woolworths store_id {store_id!r}. "
                "Use a store_id returned by get_stores()."
            )

        return store

    # ------------------------------------------------------------------
    # PRODUCT SEARCH
    # ------------------------------------------------------------------

    async def search_products(
        self,
        queries: str | list[str],
        store_id: str,
        limit: int = 48,
        page: int = 1,
    ) -> dict[str, list[Product]]:
        """
        Search one or more queries and return every result from ``page`` onward.

        ``limit`` is the Woolworths page size, not a cap on the total number of
        returned products. Woolworths currently allows at most 48 per page.
        """
        if not store_id:
            raise ValueError("store_id is required")

        store_id = str(store_id)

        if not 1 <= limit <= 48:
            raise ValueError("limit must be between 1 and 48")

        if page < 1:
            raise ValueError("page must be at least 1")

        if isinstance(queries, str):
            queries = [queries]

        # Strip blanks and remove duplicate queries while preserving order.
        queries = list(
            dict.fromkeys(
                cleaned
                for query in queries
                if isinstance(query, str) and (cleaned := query.strip())
            )
        )

        if not queries:
            return {}

        store = await self._get_store(store_id)
        expected_store_key = store["store_key"]

        # Fresh client per search_products() call keeps each request's selected
        # Woolworths store isolated from other Agora users.
        async with self._create_client() as client:
            # Select the exact pickup store once for this session.
            await self._select_store(
                client=client,
                store_id=store_id,
            )

            # Limit the number of different search terms running at once.
            # Each query can also fetch up to MAX_CONCURRENT_PAGES result pages
            # concurrently. The httpx connection pool still caps total live
            # connections for this request.
            semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SEARCHES)

            async def search_one_query(query: str):
                async with semaphore:
                    products = await self._search_one(
                        client=client,
                        query=query,
                        store_id=store_id,
                        expected_store_key=expected_store_key,
                        page_size=limit,
                        start_page=page,
                    )
                    return query, products

            results = await asyncio.gather(
                *(search_one_query(query) for query in queries)
            )

        return dict(results)

    # ------------------------------------------------------------------
    # STORE SELECTION
    # ------------------------------------------------------------------

    async def _select_store(
        self,
        client: httpx.AsyncClient,
        store_id: str,
    ) -> None:
        payload = {
            "operationName": "SetCartShoppingMode",
            "variables": {
                "setCartShoppingModeInput": {
                    "pickupLocationId": str(store_id),
                    "shoppingMode": "Pickup",
                }
            },
            "query": self.SET_SHOPPING_MODE_QUERY,
        }

        data = await self._graphql_with_retries(
            client=client,
            payload=payload,
            stage="SetCartShoppingMode",
            temporary_failure=(
                "Woolworths SetCartShoppingMode temporarily failed because "
                "an internal Woolworths service did not recover after "
                f"{self.MAX_ATTEMPTS} attempts. "
            ),
        )

        try:
            result = data["data"]["setCartShoppingMode"]
            shopping_mode = result["shoppingMode"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                "Unexpected Woolworths SetCartShoppingMode response"
            ) from exc

        validation = result.get("validationResult")
        if (
            isinstance(validation, dict)
            and validation.get("isValid") is False
        ):
            raise RuntimeError(
                "Woolworths rejected store selection: "
                f"{validation.get('failedValidations')}"
            )

        selected_store_id = shopping_mode.get("pickupLocationId")
        if (
            selected_store_id is not None
            and str(selected_store_id) != str(store_id)
        ):
            raise RuntimeError(
                "Woolworths selected the wrong pickup location. "
                f"Requested {store_id}, received {selected_store_id}."
            )

    # ------------------------------------------------------------------
    # INDIVIDUAL PRODUCT SEARCH
    # ------------------------------------------------------------------

    async def _search_one(
        self,
        client: httpx.AsyncClient,
        query: str,
        store_id: str,
        expected_store_key: str,
        page_size: int,
        start_page: int = 1,
    ) -> list[Product]:
        """Fetch all pages for one query and convert them to Product objects."""
        first_products, pagination = await self._search_page(
            client=client,
            query=query,
            page_size=page_size,
            page=start_page,
        )

        self._verify_store(
            products=first_products,
            expected_store_key=expected_store_key,
        )

        all_raw_products = list(first_products)
        total_pages = self._get_total_pages(
            pagination=pagination,
            fallback_page_size=page_size,
        )

        # totalPages is a count, not a last-page index. Therefore if there are
        # exactly 96 products at 48/page, total_pages == 2 and only page 2 is
        # requested after the first page.
        #
        # Fetch the remaining pages in small concurrent batches. asyncio.gather()
        # preserves the order of the page numbers supplied to it, so product
        # ordering stays the same as sequential pagination.
        remaining_pages = range(start_page + 1, total_pages + 1)

        for batch_start in range(
            0,
            len(remaining_pages),
            self.MAX_CONCURRENT_PAGES,
        ):
            batch = remaining_pages[
                batch_start:batch_start + self.MAX_CONCURRENT_PAGES
            ]

            page_results = await asyncio.gather(
                *(
                    self._search_page(
                        client=client,
                        query=query,
                        page_size=page_size,
                        page=page_number,
                    )
                    for page_number in batch
                )
            )

            for page_products, _ in page_results:
                self._verify_store(
                    products=page_products,
                    expected_store_key=expected_store_key,
                )
                all_raw_products.extend(page_products)

        # Sponsored products can occasionally repeat an organic result. Keep the
        # first occurrence of each SKU so Agora gets one Product per product_id.
        products: list[Product] = []
        seen_skus: set[str] = set()

        for raw_product in all_raw_products:
            sku = str(raw_product.get("sku", "")).strip()
            if not sku or sku in seen_skus:
                continue

            product = self._to_product(
                raw_product=raw_product,
                store_id=store_id,
            )
            if product is None:
                continue

            seen_skus.add(sku)
            products.append(product)

        return products

    async def _search_page(
        self,
        client: httpx.AsyncClient,
        query: str,
        page_size: int,
        page: int,
    ) -> tuple[list[dict], dict]:
        """Fetch one Woolworths search page plus its pagination metadata."""
        payload = {
            "operationName": "ProductSearch",
            "variables": {
                "searchInput": {
                    "byKeyword": {
                        "value": query,
                        "pageIndex": page - 1,
                        "pageSize": page_size,
                        "facetFilters": [],
                        "staticFilters": [],
                        "sortBy": "RELEVANCE",
                    }
                }
            },
            "query": self.PRODUCT_SEARCH_QUERY,
        }

        data = await self._graphql_with_retries(
            client=client,
            payload=payload,
            stage=f"ProductSearch for {query!r}, page {page}",
            temporary_failure=(
                "Woolworths ProductSearch temporarily failed because an "
                "internal Woolworths service could not return product pricing "
                f"after {self.MAX_ATTEMPTS} attempts. "
            ),
        )

        try:
            result = data["data"]["My"]["products"]
            raw_products = result["results"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                "Unexpected Woolworths ProductSearch response"
            ) from exc

        if not isinstance(raw_products, list):
            raise RuntimeError(
                "Woolworths product results were not a list"
            )

        products = [
            product
            for product in raw_products
            if isinstance(product, dict) and product.get("sku")
        ]

        pagination = {
            "totalCount": result.get("totalCount"),
            "pageSize": result.get("pageSize"),
            "totalPages": result.get("totalPages"),
            "currentPage": result.get("currentPage"),
        }

        return products, pagination

    @staticmethod
    def _get_total_pages(
        pagination: dict,
        fallback_page_size: int,
    ) -> int:
        """Return a safe page count, including exact page-size multiples."""
        total_pages = pagination.get("totalPages")

        try:
            total_pages = int(total_pages)
        except (TypeError, ValueError):
            total_pages = None

        if total_pages is not None and total_pages >= 0:
            return total_pages

        # Fallback if Woolworths ever omits totalPages. Ceiling division is
        # important here: 96 // 48 is exactly 2, not 3.
        try:
            total_count = max(0, int(pagination.get("totalCount") or 0))
            page_size = int(pagination.get("pageSize") or fallback_page_size)
        except (TypeError, ValueError):
            return 1

        if page_size <= 0:
            page_size = fallback_page_size

        return (total_count + page_size - 1) // page_size if total_count else 0

    @staticmethod
    def _get_promotion(
        price_info: dict,
        tags: list[dict] | None = None,
    ) -> dict | None:
        """
        Convert Woolworths promotion fields into Agora's promotion format.

        Woolworths exposes:
        - isSpecial: normal promotion
        - isClubPrice: membership/club discount
        - MemberPrice tags: member-only price in cents
        - Multibuy tags: product count and total offer price in cents
        - wasPrice: previous price
        - savedAmount: amount saved
        """
        if not isinstance(price_info, dict):
            return None

        multibuy = None

        for tag in tags if isinstance(tags, list) else []:
            if not isinstance(tag, dict):
                continue

            tag_type = tag.get("type")
            if tag_type not in (
                "MemberPrice",
                "Multibuy_FreshDeal",
                "Multibuy_Special",
                "Multibuy_LowPrice",
            ):
                continue

            decision_inputs = tag.get("decisionInputs")
            if not isinstance(decision_inputs, dict):
                continue

            if tag_type != "MemberPrice":
                if multibuy is not None:
                    continue

                quantity = WoolworthsConnector._to_float(
                    decision_inputs.get("promotionQuantity")
                )
                total_price = WoolworthsConnector._to_float(
                    decision_inputs.get("promotionalPrice")
                )
                if (
                    quantity is None
                    or quantity <= 1
                    or not quantity.is_integer()
                    or total_price is None
                    or total_price <= 0
                    or not total_price.is_integer()
                ):
                    continue

                multibuy = {
                    "type": "MULTIBUY",
                    "requires_membership": False,
                    "quantity": int(quantity),
                    "total_price": round(total_price / 100, 2),
                }
                # Keep existing member-price priority, regardless of tag order.
                continue

            member_price = WoolworthsConnector._to_float(
                decision_inputs.get("promotionalPrice")
            )
            if member_price is None or member_price <= 0:
                continue

            member_price = round(member_price / 100, 2)
            non_member_price = WoolworthsConnector._to_float(
                price_info.get("sellingPrice")
            )

            return {
                "type": "MEMBERSHIP_DISCOUNT",
                "requires_membership": True,
                "price": member_price,
                "original_price": non_member_price,
                "discount_amount": (
                    round(non_member_price - member_price, 2)
                    if non_member_price is not None
                    and non_member_price > member_price
                    else None
                ),
            }

        if multibuy is not None:
            return multibuy

        is_special = bool(price_info.get("isSpecial"))
        is_club_price = bool(price_info.get("isClubPrice"))

        if not is_special and not is_club_price:
            return None

        price = WoolworthsConnector._to_float(
            price_info.get("sellingPrice")
        )
        original_price = WoolworthsConnector._to_float(
            price_info.get("wasPrice")
        )
        saved_amount = WoolworthsConnector._to_float(
            price_info.get("savedAmount")
        )

        return {
            "type": (
                "MEMBERSHIP_DISCOUNT"
                if is_club_price
                else "DISCOUNT"
            ),
            "requires_membership": is_club_price,
            "price": price,
            "original_price": original_price,
            "discount_amount": saved_amount,
        }

    def _to_product(
        self,
        raw_product: dict,
        store_id: str,
    ) -> Product | None:
        """Convert Woolworths-specific search JSON to Agora's Product model."""
        sku = str(raw_product.get("sku", "")).strip()
        name = str(raw_product.get("productName", "")).strip()

        if not sku or not name:
            return None

        variants = raw_product.get("variants")
        variant = (
            variants[0]
            if isinstance(variants, list)
            and variants
            and isinstance(variants[0], dict)
            else {}
        )

        price_info = variant.get("variantPrice")
        if not isinstance(price_info, dict):
            price_info = {}

        price = self._to_float(price_info.get("sellingPrice"))
        if price is None:
            price = 0.0

        original_price = self._to_float(price_info.get("wasPrice"))
        if original_price is not None and original_price <= price:
            original_price = None

        promotion = self._get_promotion(price_info, raw_product.get("tags"))

        amount, quantity, unit = self._extract_amount_quantity_and_unit(
            raw_product=raw_product,
            variant=variant,
        )

        category_level_lists = self._get_category_levels(raw_product)

        category_levels = {
            "level_0": category_level_lists[0],
            "level_1": category_level_lists[1],
            "level_2": category_level_lists[2],
            "level_3": category_level_lists[3],
        }

        slug = raw_product.get("slug")
        product_url = None

        if slug:
            product_url = (
                f"{self.BASE_URL}/shop/productdetails"
                f"?stockcode={sku}&name={slug}"
            )

        return Product(
            supermarket="Woolworths",
            store_id=str(store_id),
            product_id=sku,
            name=name,
            price=price,
            brand=raw_product.get("brand") or None,
            category_levels=category_levels,
            original_price=original_price,
            promotion=promotion,
            amount=amount,
            quantity=quantity,
            unit=unit,
            barcode=None,
            image_url=raw_product.get("imageUrl") or None,
            product_url=product_url,
            available=self._is_available(raw_product),
        )

    @staticmethod
    def _get_category_levels(
        raw_product: dict,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """
        Return every Woolworths category value at levels 0 -> 3.

        A level can be either one string or multiple strings. The category
        hierarchy is already included in ProductSearch, so this creates no
        extra Woolworths API requests.
        """
        hierarchy = raw_product.get("categoryHierarchyNames")
        if not isinstance(hierarchy, dict):
            return [], [], [], []

        return (
            _clean_category_values(hierarchy.get("lvl0")),
            _clean_category_values(hierarchy.get("lvl1")),
            _clean_category_values(hierarchy.get("lvl2")),
            _clean_category_values(hierarchy.get("lvl3")),
        )

    @staticmethod
    def _is_available(raw_product: dict) -> bool:
        """Translate Woolworths availability status into a safe boolean.

        Woolworths may return the same logical status in different formats,
        for example ``"Out of Stock"``, ``"OUT_OF_STOCK"`` or
        ``"OutOfStock"``. Unknown/missing values are treated as unavailable
        so Agora never tells the user an item is in stock without evidence.
        """
        status = raw_product.get("availabilityStatus")

        if isinstance(status, bool):
            return status

        if status is None:
            return False

        # Remove spaces/punctuation entirely so all of these normalise alike:
        # "Out of Stock", "OUT_OF_STOCK", "out-of-stock", "OutOfStock".
        normalised = _AVAILABILITY_PATTERN.sub(
            "", str(status).strip().lower()
        )

        if not normalised:
            return False

        unavailable_markers = (
            "outofstock",
            "unavailable",
            "notavailable",
            "notinstock",
            "soldout",
        )
        if any(marker in normalised for marker in unavailable_markers):
            return False

        available_markers = (
            "instock",
            "lowstock",
            "limitedstock",
            "available",
        )
        if any(marker in normalised for marker in available_markers):
            return True

        # Fail closed for any new/unknown enum Woolworths introduces.
        return False

    @staticmethod
    def _extract_amount_quantity_and_unit(
        raw_product: dict,
        variant: dict,
    ) -> tuple[float | None, float | None, str | None]:
        """
        Return:
        - amount: number of items in a multipack, e.g. 6
        - quantity: size of each item, e.g. 330
        - unit: size unit, e.g. "ml"

        Variable-weight products sold per kg are represented as 1 kg and any
        minimum-order text such as "200g minimum" is deliberately ignored.
        """

        # Woolworths exposes the actual selling basis separately from the
        # shopper-facing variant text. If it is sold per kg, that is more
        # meaningful than a minimum-order value such as "200g".
        price_info = variant.get("variantPrice")
        if not isinstance(price_info, dict):
            price_info = {}

        selling_unit = _normalise_unit(price_info.get("sellingUnit"))
        unit_of_measure = _normalise_unit(variant.get("unitOfMeasure"))

        purchase_unit = variant.get("purchaseUnit")
        purchase_unit_value = None
        if isinstance(purchase_unit, dict):
            purchase_unit_value = _normalise_unit(purchase_unit.get("unit"))

        if "kg" in (selling_unit, unit_of_measure, purchase_unit_value):
            return None, 1.0, "kg"

        candidates = [
            str(variant.get("name") or "").strip(),
            str(raw_product.get("productName") or "").strip(),
        ]

        # Multipacks such as:
        # "6 x 330ml"
        # "6x330 ml"
        # "6 × 330mL"
        for text in candidates:
            match = _MULTIPACK_PATTERN.search(text)
            if match:
                return (
                    float(match.group(1)),
                    float(match.group(2)),
                    match.group(3).lower(),
                )

        # Also support text such as "6 pack 330ml" / "6pk 330ml".
        for text in candidates:
            match = _PACK_WITH_SIZE_PATTERN.search(text)
            if match:
                return (
                    float(match.group(1)),
                    float(match.group(2)),
                    match.group(3).lower(),
                )

        # Count-only packs, e.g. "12 Pack".
        for text in candidates:
            match = _PACK_PATTERN.search(text)
            if match:
                return float(match.group(1)), None, "pack"

        # Normal single product sizes such as 500ml, 1.5L or 750g.
        for text in candidates:
            matches = _SIZE_PATTERN.findall(text)
            if matches:
                quantity, unit = matches[-1]
                return None, float(quantity), unit.lower()

        # Preserve a retailer-supplied unit when there is no actual size.
        for value in (
            unit_of_measure,
            purchase_unit_value,
            selling_unit,
        ):
            if value:
                return None, None, value

        return None, None, None

    # ------------------------------------------------------------------
    # RETRIES
    # ------------------------------------------------------------------

    async def _graphql_with_retries(
        self,
        client: httpx.AsyncClient,
        payload: dict,
        stage: str,
        temporary_failure: str,
    ) -> dict:
        """Retry transient GraphQL errors using the existing HTTP retry policy."""
        operation = payload["operationName"]
        data = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            response = await self._request_with_retries(
                client=client,
                method="POST",
                url=self.GRAPHQL_URL,
                stage=stage,
                params={"op-name": operation},
                headers={"WNZX-Operation-Name": operation},
                json=payload,
            )
            data = response.json()
            graphql_errors = data.get("errors") or []

            if not graphql_errors:
                break

            transient = all(
                isinstance(error, dict)
                and isinstance(error.get("extensions"), dict)
                and error["extensions"].get("code") == "SUBREQUEST_HTTP_ERROR"
                for error in graphql_errors
            )
            if not transient:
                raise RuntimeError(
                    f"Woolworths {operation} failed: {graphql_errors}"
                )

            if attempt < self.MAX_ATTEMPTS:
                await asyncio.sleep(
                    self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                )
                continue

            raise RuntimeError(f"{temporary_failure}Errors: {graphql_errors}")

        if data is None:
            raise RuntimeError(
                f"Woolworths {operation} returned no response data"
            )

        return data

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        stage: str,
        **kwargs,
    ) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    **kwargs,
                )

                if (
                    response.status_code in {429, 500, 502, 503, 504}
                    and attempt < self.MAX_ATTEMPTS
                ):
                    await asyncio.sleep(
                        self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    )
                    continue

                response.raise_for_status()
                return response

            except (
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
            ) as exc:
                last_error = exc

                if attempt < self.MAX_ATTEMPTS:
                    await asyncio.sleep(
                        self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    )
                    continue

                break

            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:1000]
                raise RuntimeError(
                    f"Woolworths {stage} failed with HTTP "
                    f"{exc.response.status_code}. Response: {body}"
                ) from exc

            except httpx.RequestError as exc:
                raise RuntimeError(
                    f"Woolworths {stage} failed: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

        error_detail = (
            f"{type(last_error).__name__}: {last_error}"
            if last_error is not None
            else "unknown error"
        )

        raise RuntimeError(
            f"Woolworths {stage} timed out after "
            f"{self.MAX_ATTEMPTS} attempts. "
            f"Last error: {error_detail}"
        ) from last_error

    # ------------------------------------------------------------------
    # STORE VERIFICATION
    # ------------------------------------------------------------------

    def _verify_store(
        self,
        products: list,
        expected_store_key: str,
    ) -> None:
        returned_store_keys = {
            str(product["storeKey"])
            for product in products
            if product.get("storeKey") is not None
        }

        # Some empty/partial responses may not expose a storeKey.
        if not returned_store_keys:
            return

        if returned_store_keys != {str(expected_store_key)}:
            raise RuntimeError(
                "Woolworths store selection failed. "
                f"Expected storeKey {expected_store_key}, "
                f"but ProductSearch returned {sorted(returned_store_keys)}."
            )

    # ------------------------------------------------------------------
    # STORE NORMALISATION
    # ------------------------------------------------------------------

    def _normalise_store(self, raw_store: dict) -> dict | None:
        detail = raw_store.get("storeDetail", raw_store)

        if not isinstance(detail, dict):
            return None

        if detail.get("division") != "COUNTDOWN":
            return None

        # Woolworths uses two different identifiers here:
        #
        # detail["no"]
        #   -> pickupLocationId sent to SetCartShoppingMode
        #
        # detail["extra1"]
        #   -> storeKey returned by ProductSearch
        store_id = detail.get("no")
        store_key = detail.get("extra1")

        if store_id in (None, "", "null"):
            return None

        if store_key in (None, "", "null"):
            return None

        return {
            "store_id": str(store_id),
            "store_key": str(store_key),
            "name": detail.get("name"),
            "address": detail.get("addressLine1"),
            "suburb": detail.get("suburb"),
            "postcode": detail.get("postcode"),
            "region": detail.get("state"),
            "latitude": self._to_float(detail.get("latitude")),
            # Woolworths' source currently spells longitude as "longtitude".
            "longitude": self._to_float(detail.get("longtitude")),
        }

    # ------------------------------------------------------------------
    # STORE LOCATOR PARSING
    # ------------------------------------------------------------------

    def _extract_store_list(self, data) -> list:
        if isinstance(data, list):
            return data

        if not isinstance(data, dict):
            return []

        # Try likely keys first.
        for key in (
            "stores",
            "locations",
            "location",
            "results",
            "storeList",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                stores = self._extract_store_list(value)
                if stores:
                    return stores

        # Fall back to recursively scanning nested objects.
        for value in data.values():
            if isinstance(value, (dict, list)):
                stores = self._extract_store_list(value)
                if stores:
                    return stores

        return []

    @staticmethod
    def _to_float(value) -> float | None:
        if value in (None, "", "null"):
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None
