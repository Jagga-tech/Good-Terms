from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import db
from api.goodterms import router


@asynccontextmanager
async def lifespan(app):
    db.reset()
    yield


app = FastAPI(title="GoodTerms", lifespan=lifespan)
app.include_router(router)


@app.get("/api/health")
def health():
    return {"ok": True}
