import base64
import json
import time

import httpx

from .supermarket import SupermarketConnector


class NewWorldConnector(SupermarketConnector):
    BASE_WEB_URL = "https://www.newworld.co.nz"
    BASE_API_URL = "https://api-prod.newworld.co.nz/v1/edge"

    STORES_URL = f"{BASE_API_URL}/store"

    TOKEN_EXPIRY_MARGIN = 30

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self.token = None
        self.token_expires_at = 0

    async def search_products(self, query: str) -> list:
        return []

    def get_token_expiry(self, token: str) -> float | None:
        try:
            payload = token.split(".")[1]

            # Add missing Base64 padding
            payload += "=" * (-len(payload) % 4)

            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)

            return data.get("exp")

        except Exception:
            return None

    async def get_guest_token(self, client: httpx.AsyncClient) -> str:
        # Use cached token if it is still valid
        if self.token and time.time() < self.token_expires_at:
            print("Using cached token")
            print("Expires at:", self.token_expires_at)
            print(
                "Seconds remaining:",
                self.token_expires_at - time.time()
            )

            return self.token

        print("Fetching new token")

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

        # Prefer the expiry embedded in the JWT
        expiry = self.get_token_expiry(access_token)

        if expiry:
            print("Using JWT expiry:", expiry)
            print(
                "Token lifetime remaining:",
                expiry - time.time()
            )

            self.token = access_token
            self.token_expires_at = (
                expiry - self.TOKEN_EXPIRY_MARGIN
            )

        # Otherwise use expires_in supplied by the API
        elif "expires_in" in data:
            print("Using expires_in:", data["expires_in"])

            self.token = access_token
            self.token_expires_at = (
                time.time()
                + int(data["expires_in"])
                - self.TOKEN_EXPIRY_MARGIN
            )

        # If there is no expiry information, don't cache it
        else:
            print(
                "No token expiry available - "
                "token will not be cached"
            )

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

        async with httpx.AsyncClient(headers=headers) as client:
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