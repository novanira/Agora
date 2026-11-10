import asyncio

from fastapi import APIRouter

from connectors.registry import connectors


router = APIRouter(prefix="/stores", tags=["stores"])

SUPERMARKETS = ("new_world", "woolworths", "paknsave")


@router.get("/all")
async def get_all_stores():
    stores = await asyncio.gather(
        *(connectors[name].get_stores() for name in SUPERMARKETS)
    )
    return dict(zip(SUPERMARKETS, stores))