# main.py
from fastapi import FastAPI, Query
from connectors.registry import connectors
from fastapi.responses import JSONResponse

from routes.optimise import router as optimise_router
from routes.stores import router as stores_router


app = FastAPI()

app.include_router(optimise_router)
app.include_router(stores_router)

@app.get("/")
async def root():
    return "Not Found"

@app.get("/test")
async def test():
    return {
        "status": "ok",
        "number": 1236767676776767676767677777777777777769999999,
        'i':"sa"
    }

# -----------------------
# New World test routes
# -----------------------

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


# ------------------------
# Woolworths test routes
# ------------------------

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
        matches = await connectors[
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

    return JSONResponse(
        content={
            term: [vars(product) for product in products]
            for term, products in matches.items()
        },
    )


# ----------------------
# PakNSave test routes
# ----------------------

@app.get("/test-paknsave/stores")
async def test_paknsave_stores():
    return await connectors["paknsave"].get_stores()

@app.get("/test-paknsave/products")
async def test_paknsave_products(
    store_id: str,
    query: list[str] = Query(...),
):
    return await connectors["paknsave"].search_products(
        queries=query,
        store_id=store_id,
    )



