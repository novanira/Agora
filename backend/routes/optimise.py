import asyncio
import logging
import os
import time

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from connectors.registry import connectors

router = APIRouter()
logger = logging.getLogger(__name__)

TURSO_DATABASE_URL = "libsql://agora-novanira491.aws-us-west-2.turso.io"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


async def _load_identities(product_ids: dict[str, set[str]]) -> dict:
    # Every cross-retailer match must include an ID from each retailer, so
    # looking up the smaller set finds every possible match in these results.
    if not all(product_ids.values()):
        return {}

    supermarket = min(product_ids, key=lambda name: len(product_ids[name]))
    column = "foodstuffs_id" if supermarket == "new_world" else "woolworths_id"
    ids = sorted(product_ids[supermarket])
    requests = []

    for start in range(0, len(ids), 400):
        batch = ids[start:start + 400]
        placeholders = ",".join("?" for _ in batch)
        requests.append({
            "type": "execute",
            "stmt": {
                "sql": (
                    "SELECT id, barcode, foodstuffs_id, woolworths_id "
                    f"FROM product_identities WHERE {column} IN ({placeholders})"
                ),
                "args": [{"type": "text", "value": value} for value in batch],
            },
        })

    url = os.getenv("TURSO_DATABASE_URL", TURSO_DATABASE_URL)
    url = url.replace("libsql://", "https://", 1).rstrip("/")
    token = os.environ["TURSO_AUTH_TOKEN"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{url}/v2/pipeline",
            headers={"Authorization": f"Bearer {token}"},
            json={"requests": requests + [{"type": "close"}]},
        )
        response.raise_for_status()
        results = response.json()["results"]

    if len(results) != len(requests) + 1 or any(
        result.get("type") != "ok" for result in results
    ):
        raise RuntimeError("Turso identity lookup failed.")

    identities = {}
    for result in results[:-1]:
        for row in result["response"]["result"]["rows"]:
            identity = (int(row[0]["value"]), row[1].get("value"))
            for supermarket, index in (("new_world", 2), ("woolworths", 3)):
                product_id = row[index].get("value")
                if product_id is not None:
                    identities[(supermarket, product_id)] = identity

    return identities


def _match_products(stores: list[dict], queries: list[str], identities: dict) -> dict:
    matches = {}
    for query in queries:
        groups = {}
        for store in stores:
            if store["products"] is None:
                continue

            for product in store["products"][query]:
                identity = identities.get(
                    (store["supermarket"], str(product["product_id"]))
                )
                if identity is None:
                    continue

                identity_id, barcode = identity
                group = groups.setdefault(identity_id, {
                    "identity_id": identity_id,
                    "barcode": barcode,
                    "products": [],
                })
                # Full Product fields remain in stores; matches only need references.
                group["products"].append({
                    "supermarket": store["supermarket"],
                    "store_id": store["store_id"],
                    "product_id": product["product_id"],
                })

        matches[query] = [
            group for group in groups.values()
            if len({product["supermarket"] for product in group["products"]}) == 2
        ]

    return matches


@router.get("/optimise")
async def optimise(
    query: list[str] = Query(...),
    new_world_store_ids: list[str] = Query(default=[]),
    woolworths_store_ids: list[str] = Query(default=[]),
):
    """Fetch up to 48 products per query/store and match using existing identities.

    The response contains stores and cross-retailer matches grouped by query.
    Failed stores have products=null. A database failure returns matches=null
    and matching_error while preserving the fetched store results.
    """
    queries = _unique(query)
    stores = [
        (supermarket, store_id)
        for supermarket, store_ids in (
            ("new_world", new_world_store_ids),
            ("woolworths", woolworths_store_ids),
        )
        for store_id in _unique(store_ids)
    ]
    if not queries or not stores:
        raise HTTPException(422, "Provide at least one query and one store ID.")

    started = time.perf_counter()
    semaphore = asyncio.Semaphore(3)

    async def search_store(supermarket: str, store_id: str):
        result = {"supermarket": supermarket, "store_id": store_id, "products": None}

        async with semaphore:
            store_started = time.perf_counter()
            try:
                matches = await connectors[supermarket].search_products(
                    queries=queries,
                    store_id=store_id,
                    limit=48,
                    page=1,
                    pages=1,
                )
                result["products"] = {
                    term: [vars(product) for product in matches.get(term, [])[:48]]
                    for term in queries
                }
            except Exception:
                logger.exception("Product search failed for %s store %s", supermarket, store_id)
                result["error"] = "Product search failed for this store."
            finally:
                logger.info(
                    "optimise supermarket=%s store_id=%s search_ms=%.1f",
                    supermarket,
                    store_id,
                    (time.perf_counter() - store_started) * 1000,
                )

        return result

    results = await asyncio.gather(
        *(search_store(supermarket, store_id) for supermarket, store_id in stores)
    )
    product_ids = {"new_world": set(), "woolworths": set()}
    for store in results:
        if store["products"] is not None:
            product_ids[store["supermarket"]].update(
                str(product["product_id"])
                for products in store["products"].values()
                for product in products
            )

    content = {"stores": results, "matches": None}
    matching_started = time.perf_counter()
    try:
        identities = await _load_identities(product_ids)
        content["matches"] = _match_products(results, queries, identities)
    except Exception:
        logger.exception("Product identity matching failed")
        content["matching_error"] = "Product matching is currently unavailable."
    finally:
        logger.info(
            "optimise matching_ms=%.1f",
            (time.perf_counter() - matching_started) * 1000,
        )

    response = JSONResponse(content=content)
    logger.info(
        "optimise queries=%d stores=%d total_ms=%.1f",
        len(queries),
        len(stores),
        (time.perf_counter() - started) * 1000,
    )
    return response