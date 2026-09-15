# main.py
from fastapi import FastAPI
from connectors.registry import connectors

app = FastAPI()

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

@app.get("/test-new-world")
async def test_new_world():
    return await connectors["new_world"].get_stores()
