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

            fulfilment {
                fulfilmentProposition {
                    store {
                        storeId
                        name
                    }

                    storeId
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

    def get_headers(self) -> dict:
        return {
            "User-Agent": self.USER_AGENT,
            "Accept": (
                "application/graphql-response+json,"
                "application/json;q=0.9"
            ),
            "Content-Type": "application/json",
            "Accept-Language": "en-NZ,en;q=0.9",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/",
        }

    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self.get_headers(),
            follow_redirects=True,
            timeout=20.0,
        )

    async def get_stores(self) -> list:
        """
        Return selectable Woolworths supermarket stores.

        store_id:
            Woolworths pickupLocationId used by
            SetCartShoppingMode.

        store_key:
            Expected storeKey returned by ProductSearch.

        Example:
            {
                "store_id": "9011",
                "store_key": "9015",
                "name": "Paeroa Woolworths",
                ...
            }
        """

        async with httpx.AsyncClient(
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json",
            },
            follow_redirects=True,
            timeout=20.0,
        ) as client:
            response = await client.get(
                self.STORE_LOCATOR_URL
            )

            response.raise_for_status()

            data = response.json()

        raw_stores = self._extract_store_list(data)

        stores = []

        for raw_store in raw_stores:
            if not isinstance(raw_store, dict):
                continue

            store = self._normalise_store(raw_store)

            if store is not None:
                stores.append(store)

        self._stores_by_id = {
            store["store_id"]: store
            for store in stores
        }

        return stores

    async def search_products(
        self,
        queries: str | list[str],
        store_id: str,
        limit: int = 48,
        page: int = 1,
    ) -> dict[str, list]:
        """
        Search one specific Woolworths store.

        `store_id` must be a value returned by get_stores().

        Examples:

            await search_products(
                "milk",
                store_id="9011",
            )

        or:

            await search_products(
                ["milk", "eggs", "bread"],
                store_id="9011",
            )
        """

        if not store_id:
            raise ValueError("store_id is required")

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
                if query.strip()
            )
        )

        if not queries:
            return {}

        store = await self._get_store(store_id)

        expected_store_key = store["store_key"]

        async with self._create_client() as client:

            # Create anonymous Woolworths guest session.
            await self._initialise_session(client)

            # Select exact store using the modern GraphQL mutation.
            await self._select_store(
                client=client,
                store_id=store_id,
            )

            semaphore = asyncio.Semaphore(
                self.MAX_CONCURRENT_SEARCHES
            )

            async def search(query: str):
                async with semaphore:
                    products = await self._search_one(
                        client=client,
                        query=query,
                        limit=limit,
                        page=page,
                    )

                    self._verify_store(
                        products=products,
                        expected_store_key=expected_store_key,
                    )

                    return query, products

            results = await asyncio.gather(
                *(
                    search(query)
                    for query in queries
                )
            )

        return dict(results)

    async def _get_store(
        self,
        store_id: str,
    ) -> dict:
        """
        Resolve a store_id into the store metadata returned
        by get_stores().
        """

        store = self._stores_by_id.get(store_id)

        if store is None:
            await self.get_stores()

            store = self._stores_by_id.get(store_id)

        if store is None:
            raise ValueError(
                f"Unknown Woolworths store_id "
                f"{store_id!r}. "
                "Use a store_id returned by get_stores()."
            )

        return store

    async def _initialise_session(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """
        Load Woolworths once so the client receives the
        anonymous guest/session cookies required by GraphQL.
        """

        response = await client.get(
            self.BASE_URL
        )

        response.raise_for_status()

    async def _select_store(
        self,
        client: httpx.AsyncClient,
        store_id: str,
    ) -> None:
        """
        Select a Woolworths pickup store using the same
        SetCartShoppingMode mutation used by the website.

        store_id is Woolworths' pickupLocationId.
        """

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

        response = await client.post(
            self.GRAPHQL_URL,
            params={
                "op-name": "SetCartShoppingMode",
            },
            headers={
                "WNZX-Operation-Name":
                    "SetCartShoppingMode",
            },
            json=payload,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("errors"):
            raise RuntimeError(
                "Woolworths SetCartShoppingMode "
                f"failed: {data['errors']}"
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
            isinstance(validation, dict)
            and validation.get("isValid") is False
        ):
            raise RuntimeError(
                "Woolworths rejected store selection: "
                f"{validation.get('failedValidations')}"
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
                "Woolworths selected the wrong "
                "pickup location. "
                f"Requested {store_id}, "
                f"received {selected_store_id}."
            )

    async def _search_one(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
        page: int,
    ) -> list:
        """
        Search products using the shopping/store context
        already selected on the current client.
        """

        payload = {
            "operationName": "ProductSearch",

            "variables": {
                "searchInput": {
                    "byKeyword": {
                        "value": query,
                        "pageIndex": page - 1,
                        "pageSize": limit,
                        "facetFilters": [],
                        "staticFilters": [],
                        "sortBy": "RELEVANCE",
                    }
                }
            },

            "query": self.PRODUCT_SEARCH_QUERY,
        }

        response = await client.post(
            self.GRAPHQL_URL,
            params={
                "op-name": "ProductSearch",
            },
            headers={
                "WNZX-Operation-Name":
                    "ProductSearch",
            },
            json=payload,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("errors"):
            raise RuntimeError(
                "Woolworths ProductSearch failed: "
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

        if not isinstance(products, list):
            raise RuntimeError(
                "Woolworths product results "
                "were not a list"
            )

        # Woolworths sometimes inserts empty objects
        # into sponsored/ad positions.
        return [
            product
            for product in products
            if (
                isinstance(product, dict)
                and product.get("sku")
            )
        ]

    def _verify_store(
        self,
        products: list,
        expected_store_key: str,
    ) -> None:
        """
        Ensure ProductSearch is actually returning prices
        for the store selected above.
        """

        returned_store_keys = {
            str(product["storeKey"])

            for product in products

            if product.get("storeKey")
            is not None
        }

        # Nothing to verify for an empty search.
        if not returned_store_keys:
            return

        if returned_store_keys != {
            str(expected_store_key)
        }:
            raise RuntimeError(
                "Woolworths store selection failed. "
                f"Expected storeKey "
                f"{expected_store_key}, "
                f"but ProductSearch returned "
                f"{sorted(returned_store_keys)}."
            )

    def _normalise_store(
        self,
        raw_store: dict,
    ) -> dict | None:
        """
        Store locator mapping inferred from the current
        Woolworths data + captured SetCartShoppingMode call:

        no:
            pickupLocationId used by the current GraphQL API.

        extra1:
            storeKey expected from ProductSearch.

        Only normal COUNTDOWN supermarket records are used.
        """

        detail = raw_store.get(
            "storeDetail",
            raw_store,
        )

        if not isinstance(detail, dict):
            return None

        if detail.get("division") != "COUNTDOWN":
            return None

        store_id = detail.get("no")
        store_key = detail.get("extra1")

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
            "store_id": str(store_id),

            "store_key": str(store_key),

            "name": detail.get("name"),

            "address": detail.get(
                "addressLine1"
            ),

            "suburb": detail.get(
                "suburb"
            ),

            "postcode": detail.get(
                "postcode"
            ),

            "region": detail.get(
                "state"
            ),

            "latitude": self._to_float(
                detail.get("latitude")
            ),

            # The store-locator API actually spells
            # longitude as "longtitude".
            "longitude": self._to_float(
                detail.get("longtitude")
            ),
        }

    def _extract_store_list(
        self,
        data,
    ) -> list:
        if isinstance(data, list):
            return data

        if not isinstance(data, dict):
            return []

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
                stores = self._extract_store_list(
                    value
                )

                if stores:
                    return stores

        for value in data.values():
            if isinstance(
                value,
                (dict, list),
            ):
                stores = self._extract_store_list(
                    value
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