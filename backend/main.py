# main.py
from fastapi import FastAPI, Query
from connectors.registry import connectors
from fastapi.responses import JSONResponse


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

@app.get("/test-new-world/stores")
async def test_new_world_stores():
    return await connectors["new_world"].get_stores()


@app.get("/test-new-world/products")
async def test_new_world_products(
    store_id: str,
    query: list[str] = Query(...),
):
    return await connectors["new_world"].search_products(
        queries=query,
        store_id=store_id,
    )


# -------------------------
# Woolworths test routes
# -------------------------

@app.get("/test-woolworths/stores")
async def test_woolworths_stores():
    return await connectors[
        "woolworths"
    ].get_stores()


@app.get("/test-woolworths/products")
async def test_woolworths_products(
    store_id: str,
    query: list[str] = Query(...),
):
    try:
        return await connectors[
            "woolworths"
        ].search_products(
            queries=query,
            store_id=store_id,
        )

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": type(exc).__name__,
                "message": str(exc),
            },
        )