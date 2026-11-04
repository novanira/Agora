import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from connectors.registry import connectors

router = APIRouter()
logger = logging.getLogger(__name__)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


@router.get("/optimise")
async def optimise(
    query: list[str] = Query(...),
    new_world_store_ids: list[str] = Query(default=[]),
    woolworths_store_ids: list[str] = Query(default=[]),
):
    """Fetch one page of up to 48 matches per query for each selected store.

    Repeat query and store-ID parameters to supply lists. Successful stores
    return products grouped by query; failed stores return products=null
    and an error message.
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
        result = {
            "supermarket": supermarket,
            "store_id": store_id,
            "products": None,
        }

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
                    term: [
                        vars(product)
                        for product in matches.get(term, [])[:48]
                    ]
                    for term in queries
                }
            except Exception:
                logger.exception(
                    "Product search failed for %s store %s",
                    supermarket,
                    store_id,
                )
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
    response = JSONResponse(content=results)
    logger.info(
        "optimise queries=%d stores=%d total_ms=%.1f",
        len(queries),
        len(stores),
        (time.perf_counter() - started) * 1000,
    )
    return response