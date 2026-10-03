import asyncio
import base64
import json
import re
import time

import httpx

from .supermarket import SupermarketConnector

class PakNSaveConnector(SupermarketConnector):
    BASE_WEB_URL = "https://www.paknsave.co.nz"
    BASE_API_URL = "https://api-prod.paknsave.co.nz/v1/edge"

    PRODUCTS_URL = f"{BASE_API_URL}/search/paginated/products"

    TOKEN_EXPIRY_MARGIN = 30

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
    
    def __init__(self):
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()


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

    async def get_stores(self):
        async with self._create_client() as client:
            token = await self.get_guest_token(client)

            response = await client.get(
                f"{self.BASE_API_URL}/store", 
                headers={"Authorization": f"Bearer {token}"}
            )

            response.raise_for_status()

            return response.json().get("stores", [])


    def search_products(self):
        pass