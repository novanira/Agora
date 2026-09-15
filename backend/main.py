# main.py
from fastapi import FastAPI

from connectors.new_world import router as search_router

app = FastAPI()
app.include_router(search_router)

@app.get("/")
async def root():
    return {"message": "Agora API is running4444"}

@app.get("/test")
async def test():
    return {
        "status": "ok",
        "number": 12367676767767676767676777777777777777,
    }
