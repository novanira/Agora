from fastapi import APIRouter

router = APIRouter()

@router.get("/optimise")
async def optimise():
    return {"status": "ok"}