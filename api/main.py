from fastapi import FastAPI

app = FastAPI(title="GoodTerms")


@app.get("/api/health")
def health():
    return {"ok": True}
