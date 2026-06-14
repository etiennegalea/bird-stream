from litestar import get


@get("/health", tags=["health"], sync_to_thread=False)
def health_check() -> dict:
    return {"status": "ok"}
