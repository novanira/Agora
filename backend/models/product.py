class Product:
    CATEGORY_LEVEL_KEYS = (
        "level_0",
        "level_1",
        "level_2",
        "level_3",
    )

    def __init__(
        self,
        supermarket: str,
        store_id: str,
        product_id: str,
        name: str,
        price: float,
        brand: str | None = None,
        category_levels: dict[str, list[str]] | None = None,
        original_price: float | None = None,
        amount: float | None = None,
        quantity: float | None = None,
        unit: str | None = None,
        barcode: str | None = None,
        image_url: str | None = None,
        product_url: str | None = None,
        available: bool = True,
    ):
        self.supermarket = supermarket
        self.store_id = store_id
        self.product_id = product_id
        self.name = name
        self.price = price

        self.brand = brand

        # Keep one canonical category representation. This avoids having
        # category/category_level_0/... drift out of sync with the arrays.
        self.category_levels = self._normalise_category_levels(
            category_levels
        )
        self.categories = self._deepest_categories(
            self.category_levels
        )

        self.original_price = original_price

        self.amount = amount
        self.quantity = quantity
        self.unit = unit

        self.barcode = barcode
        self.image_url = image_url
        self.product_url = product_url

        self.available = available

    @classmethod
    def _normalise_category_levels(
        cls,
        category_levels: dict[str, list[str]] | None,
    ) -> dict[str, list[str]]:
        normalised = {
            key: []
            for key in cls.CATEGORY_LEVEL_KEYS
        }

        if not isinstance(category_levels, dict):
            return normalised

        for key in cls.CATEGORY_LEVEL_KEYS:
            values = category_levels.get(key)

            if isinstance(values, str):
                values = [values]

            if not isinstance(values, (list, tuple, set)):
                continue

            seen: set[str] = set()

            for value in values:
                if not isinstance(value, str):
                    continue

                value = value.strip()

                if not value or value in seen:
                    continue

                seen.add(value)
                normalised[key].append(value)

        return normalised

    @classmethod
    def _deepest_categories(
        cls,
        category_levels: dict[str, list[str]],
    ) -> list[str]:
        for key in reversed(cls.CATEGORY_LEVEL_KEYS):
            values = category_levels.get(key, [])

            if values:
                return list(values)

        return []

    def to_dict(self):
        return {
            "supermarket": self.supermarket,
            "store_id": self.store_id,
            "product_id": self.product_id,
            "name": self.name,
            "price": self.price,
            "brand": self.brand,
            "categories": list(self.categories),
            "category_levels": {
                key: list(values)
                for key, values in self.category_levels.items()
            },
            "original_price": self.original_price,
            "amount": self.amount,
            "quantity": self.quantity,
            "unit": self.unit,
            "barcode": self.barcode,
            "image_url": self.image_url,
            "product_url": self.product_url,
            "available": self.available,
        }

    def __repr__(self):
        return (
            f"Product("
            f"name={self.name!r}, "
            f"price={self.price}, "
            f"supermarket={self.supermarket!r}, "
            f"store_id={self.store_id!r}"
            f")"
        )
