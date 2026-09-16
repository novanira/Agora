import asyncio

import httpx

from .supermarket import SupermarketConnector


class WoolworthsConnector(SupermarketConnector):
    BASE_URL = "https://www.woolworths.co.nz"
    GRAPHQL_URL = f"{BASE_URL}/api/graphql"

    STORE_LOCATOR_URL = (
        "https://contact.woolworths.com.au/storelocator/service/"
        "corporateinfo/country/nz/division/all/"
        "tradinghours/standard/weeks/1/json"
    )

    MAX_CONCURRENT_SEARCHES = 5

    # Retry settings
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
        setCartShoppingMode(
            input: $setCartShoppingModeInput
        ) {
            shoppingMode {
                mode
                pickupLocationId

                pickupLocation {
                    id
                    name
                }
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
    query ProductSearch(
        $searchInput: CompositeSearchInput!
    ) {
        My {
            products(searchInput: $searchInput) {
                results {
                    ... on ProductSummary {
                        __typename
                        sku
                        productName
                        slug
                        imageUrl
                        storeKey
                        brand

                        categoryHierarchyNames {
                            lvl0
                            lvl1
                            lvl2
                            lvl3
                        }

                        variants {
                            variantKey
                            name
                            unitOfMeasure

                            purchaseUnit {
                                unit
                            }

                            variantPrice {
                                currency
                                isSpecial
                                isClubPrice
                                isBoostOffer
                                sellingUnit
                                sellingPrice
                                savedAmount
                                wasPrice
                                cupPrice
                                cupUnit
                            }
                        }
                    }

                    ... on SponsoredProduct {
                        __typename
                        sku
                        productName
                        slug
                        imageUrl
                        storeKey
                        brand

                        categoryHierarchyNames {
                            lvl0
                            lvl1
                            lvl2
                            lvl3
                        }

                        variants {
                            variantKey
                            name
                            unitOfMeasure

                            purchaseUnit {
                                unit
                            }

                            variantPrice {
                                currency
                                isSpecial
                                isClubPrice
                                isBoostOffer
                                sellingUnit
                                sellingPrice
                                savedAmount
                                wasPrice
                                cupPrice
                                cupUnit
                            }
                        }
                    }
                }

                totalCount
                pageSize
                totalPages
                currentPage
            }
        }
    }
    """

    def __init__(self):
        self._stores_by_id: dict[str, dict] = {}

        # Prevent several simultaneous requests on a fresh
        # Render instance from all calling get_stores().
        self._stores_lock = asyncio.Lock()

    # ---------------------------------------------------------
    # HTTP CLIENT
    # ---------------------------------------------------------

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
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),

            follow_redirects=True,
        )

    # ---------------------------------------------------------
    # STORES
    # ---------------------------------------------------------

    async def get_stores(self) -> list:
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

        stores = []

        for raw_store in raw_stores:
            if not isinstance(raw_store, dict):
                continue

            store = self._normalise_store(
                raw_store
            )

            if store is not None:
                stores.append(store)

        self._stores_by_id = {
            store["store_id"]: store
            for store in stores
        }

        return stores

    async def _get_store(
        self,
        store_id: str,
    ) -> dict:

        store = self._stores_by_id.get(
            store_id
        )

        if store is not None:
            return store

        async with self._stores_lock:

            # Check again because another request might
            # have filled the cache while we waited.
            store = self._stores_by_id.get(
                store_id
            )

            if store is None:
                await self.get_stores()

                store = self._stores_by_id.get(
                    store_id
                )

        if store is None:
            raise ValueError(
                f"Unknown Woolworths store_id "
                f"{store_id!r}. "
                "Use a store_id returned by get_stores()."
            )

        return store

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
            raise ValueError(
                "store_id is required"
            )

        store_id = str(store_id)

        if not 1 <= limit <= 48:
            raise ValueError(
                "limit must be between 1 and 48"
            )

        if page < 1:
            raise ValueError(
                "page must be at least 1"
            )

        if isinstance(queries, str):
            queries = [queries]

        queries = list(
            dict.fromkeys(
                query.strip()
                for query in queries
                if (
                    isinstance(query, str)
                    and query.strip()
                )
            )
        )

        if not queries:
            return {}

        store = await self._get_store(
            store_id
        )

        expected_store_key = (
            store["store_key"]
        )

        async with self._create_client() as client:

            # Step 1:
            # select the exact Woolworths store directly.
            #
            # Do not make a separate request to the homepage first.
            # SetCartShoppingMode is the first request in this client
            # session, and httpx will retain any cookies Woolworths
            # returns for the following ProductSearch requests.
            await self._select_store(
                client=client,
                store_id=store_id,
            )

            # Step 2:
            # search all products using the SAME
            # session + store context.
            semaphore = asyncio.Semaphore(
                self.MAX_CONCURRENT_SEARCHES
            )

            async def search(
                query: str,
            ):
                async with semaphore:

                    products = (
                        await self._search_one(
                            client=client,
                            query=query,
                            limit=limit,
                            page=page,
                        )
                    )

                    self._verify_store(
                        products=products,
                        expected_store_key=(
                            expected_store_key
                        ),
                    )

                    return query, products

            results = await asyncio.gather(
                *(
                    search(query)
                    for query in queries
                )
            )

        return dict(results)

    # ---------------------------------------------------------
    # STORE SELECTION
    # ---------------------------------------------------------

    async def _select_store(
        self,
        client: httpx.AsyncClient,
        store_id: str,
    ) -> None:

        payload = {
            "operationName":
                "SetCartShoppingMode",

            "variables": {
                "setCartShoppingModeInput": {
                    "pickupLocationId":
                        str(store_id),

                    "shoppingMode":
                        "Pickup",
                }
            },

            "query":
                self.SET_SHOPPING_MODE_QUERY,
        }

        response = await (
            self._request_with_retries(
                client=client,
                method="POST",
                url=self.GRAPHQL_URL,
                stage=(
                    "SetCartShoppingMode"
                ),

                params={
                    "op-name":
                        "SetCartShoppingMode",
                },

                headers={
                    "WNZX-Operation-Name":
                        "SetCartShoppingMode",
                },

                json=payload,
            )
        )

        data = response.json()

        if data.get("errors"):

            raise RuntimeError(
                "Woolworths "
                "SetCartShoppingMode failed: "
                f"{data['errors']}"
            )

        try:
            result = (
                data["data"]
                ["setCartShoppingMode"]
            )

            shopping_mode = (
                result["shoppingMode"]
            )

        except (
            KeyError,
            TypeError,
        ) as exc:

            raise RuntimeError(
                "Unexpected Woolworths "
                "SetCartShoppingMode response"
            ) from exc

        validation = result.get(
            "validationResult"
        )

        if (
            isinstance(
                validation,
                dict,
            )
            and validation.get(
                "isValid"
            ) is False
        ):

            raise RuntimeError(
                "Woolworths rejected "
                "store selection: "
                f"{validation.get(
                    'failedValidations'
                )}"
            )

        selected_store_id = (
            shopping_mode.get(
                "pickupLocationId"
            )
        )

        if (
            selected_store_id is not None
            and str(selected_store_id)
            != str(store_id)
        ):

            raise RuntimeError(
                "Woolworths selected "
                "the wrong pickup location. "
                f"Requested {store_id}, "
                f"received "
                f"{selected_store_id}."
            )

    # ---------------------------------------------------------
    # INDIVIDUAL SEARCH
    # ---------------------------------------------------------

    async def _search_one(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
        page: int,
    ) -> list:

        payload = {
            "operationName":
                "ProductSearch",

            "variables": {
                "searchInput": {
                    "byKeyword": {
                        "value":
                            query,

                        "pageIndex":
                            page - 1,

                        "pageSize":
                            limit,

                        "facetFilters":
                            [],

                        "staticFilters":
                            [],

                        "sortBy":
                            "RELEVANCE",
                    }
                }
            },

            "query":
                self.PRODUCT_SEARCH_QUERY,
        }

        response = await (
            self._request_with_retries(
                client=client,
                method="POST",
                url=self.GRAPHQL_URL,

                stage=(
                    "ProductSearch "
                    f"for {query!r}"
                ),

                params={
                    "op-name":
                        "ProductSearch",
                },

                headers={
                    "WNZX-Operation-Name":
                        "ProductSearch",
                },

                json=payload,
            )
        )

        data = response.json()

        if data.get("errors"):

            raise RuntimeError(
                "Woolworths "
                "ProductSearch failed: "
                f"{data['errors']}"
            )

        try:
            products = (
                data["data"]
                ["My"]
                ["products"]
                ["results"]
            )

        except (
            KeyError,
            TypeError,
        ) as exc:

            raise RuntimeError(
                "Unexpected Woolworths "
                "ProductSearch response"
            ) from exc

        if not isinstance(
            products,
            list,
        ):

            raise RuntimeError(
                "Woolworths product results "
                "were not a list"
            )

        return [
            product

            for product in products

            if (
                isinstance(
                    product,
                    dict,
                )
                and product.get("sku")
            )
        ]

    # ---------------------------------------------------------
    # RETRY HELPER
    # ---------------------------------------------------------

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        stage: str,
        **kwargs,
    ) -> httpx.Response:

        last_error = None

        for attempt in range(
            1,
            self.MAX_ATTEMPTS + 1,
        ):

            try:
                response = await client.request(
                    method,
                    url,
                    **kwargs,
                )

                # Retry temporary upstream failures.
                if (
                    response.status_code
                    in {
                        429,
                        500,
                        502,
                        503,
                        504,
                    }
                    and attempt
                    < self.MAX_ATTEMPTS
                ):

                    await asyncio.sleep(
                        self.RETRY_BASE_DELAY
                        * (
                            2
                            ** (
                                attempt - 1
                            )
                        )
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

                if (
                    attempt
                    < self.MAX_ATTEMPTS
                ):

                    await asyncio.sleep(
                        self.RETRY_BASE_DELAY
                        * (
                            2
                            ** (
                                attempt - 1
                            )
                        )
                    )

                    continue

                break

            except httpx.HTTPStatusError as exc:

                body = (
                    exc.response.text[:1000]
                )

                raise RuntimeError(
                    f"Woolworths {stage} "
                    f"failed with HTTP "
                    f"{exc.response.status_code}. "
                    f"Response: {body}"
                ) from exc

            except httpx.RequestError as exc:

                raise RuntimeError(
                    f"Woolworths {stage} "
                    "failed: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ) from exc

        error_detail = (
            f"{type(last_error).__name__}: {last_error}"
            if last_error
            else "unknown error"
        )

        raise RuntimeError(
            f"Woolworths {stage} timed out after "
            f"{self.MAX_ATTEMPTS} attempts. "
            f"Last error: {error_detail}"
        ) from last_error

    # ---------------------------------------------------------
    # STORE VERIFICATION
    # ---------------------------------------------------------

    def _verify_store(
        self,
        products: list,
        expected_store_key: str,
    ) -> None:

        returned_store_keys = {
            str(
                product["storeKey"]
            )

            for product in products

            if product.get(
                "storeKey"
            ) is not None
        }

        if not returned_store_keys:
            return

        if (
            returned_store_keys
            != {
                str(
                    expected_store_key
                )
            }
        ):

            raise RuntimeError(
                "Woolworths store selection "
                "failed. "
                f"Expected storeKey "
                f"{expected_store_key}, "
                "but ProductSearch returned "
                f"{sorted(
                    returned_store_keys
                )}."
            )

    # ---------------------------------------------------------
    # STORE NORMALISATION
    # ---------------------------------------------------------

    def _normalise_store(
        self,
        raw_store: dict,
    ) -> dict | None:

        detail = raw_store.get(
            "storeDetail",
            raw_store,
        )

        if not isinstance(
            detail,
            dict,
        ):
            return None

        if (
            detail.get("division")
            != "COUNTDOWN"
        ):
            return None

        # Verified current mapping:
        #
        # no
        #   -> pickupLocationId used by
        #      SetCartShoppingMode
        #
        # extra1
        #   -> storeKey returned by
        #      ProductSearch

        store_id = detail.get("no")

        store_key = detail.get(
            "extra1"
        )

        if store_id in (
            None,
            "",
            "null",
        ):
            return None

        if store_key in (
            None,
            "",
            "null",
        ):
            return None

        return {
            "store_id":
                str(store_id),

            "store_key":
                str(store_key),

            "name":
                detail.get("name"),

            "address":
                detail.get(
                    "addressLine1"
                ),

            "suburb":
                detail.get("suburb"),

            "postcode":
                detail.get(
                    "postcode"
                ),

            "region":
                detail.get("state"),

            "latitude":
                self._to_float(
                    detail.get(
                        "latitude"
                    )
                ),

            # Woolworths' API spells
            # longitude as "longtitude".
            "longitude":
                self._to_float(
                    detail.get(
                        "longtitude"
                    )
                ),
        }

    # ---------------------------------------------------------
    # STORE LOCATOR PARSING
    # ---------------------------------------------------------

    def _extract_store_list(
        self,
        data,
    ) -> list:

        if isinstance(data, list):
            return data

        if not isinstance(
            data,
            dict,
        ):
            return []

        for key in (
            "stores",
            "locations",
            "location",
            "results",
            "storeList",
        ):

            value = data.get(key)

            if isinstance(
                value,
                list,
            ):
                return value

            if isinstance(
                value,
                dict,
            ):

                stores = (
                    self._extract_store_list(
                        value
                    )
                )

                if stores:
                    return stores

        for value in data.values():

            if isinstance(
                value,
                (dict, list),
            ):

                stores = (
                    self._extract_store_list(
                        value
                    )
                )

                if stores:
                    return stores

        return []

    @staticmethod
    def _to_float(
        value,
    ) -> float | None:

        if value in (
            None,
            "",
            "null",
        ):
            return None

        try:
            return float(value)

        except (
            TypeError,
            ValueError,
        ):
            return None