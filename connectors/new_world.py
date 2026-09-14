# testing, not real code for this file

from fastapi import APIRouter

router = APIRouter()

@router.get("/search")
async def search(q: str):
    return {
        "query": q,
        "products": []
    }
