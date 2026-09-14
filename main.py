# main.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Agora API is running4444"}

@app.get("/test")
async def test():
    return {
        "status": "ok",
        "number": 123,
    }
