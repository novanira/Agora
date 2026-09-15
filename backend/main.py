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
        "number": 1236767676776767676767677777777777777769999999,
        'i':"s"
    }
