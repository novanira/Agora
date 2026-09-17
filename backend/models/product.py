class Product:
    def __init__(
        self,
        supermarket: str,
        store_id: str,
        product_id: str,
        name: str,
        price: float,
        brand: str | None = None,
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
        self.original_price = original_price

        self.amount = amount
        self.quantity = quantity
        self.unit = unit

        self.barcode = barcode
        self.image_url = image_url
        self.product_url = product_url

        self.available = available

    def to_dict(self):
        return {
            "supermarket": self.supermarket,
            "store_id": self.store_id,
            "product_id": self.product_id,
            "name": self.name,
            "price": self.price,
            "brand": self.brand,
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
