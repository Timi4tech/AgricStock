import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .database import initialize_database
from .api.routes import router
from .core.rate_limit import enforce_rate_limit
from .core.request_context import resolve_request_id, store_request_metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="AgroStock API",
    version="0.3.0",
    description="Stock records for Nigerian agribusinesses",
    lifespan=lifespan,
)
origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context_and_rate_limit(request: Request, call_next):
    request_id = resolve_request_id(request)
    request.state.request_id = request_id

    # Health checks stay available during dependency outages. Application requests
    # require Upstash: no in-memory fallback is used for rate limits or request IDs.
    if request.url.path == "/health":
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    try:
        await store_request_metadata(request_id, request)
        await enforce_rate_limit(request)
    except Exception as exc:
        status_code = getattr(exc, "status_code", 503)
        detail = getattr(exc, "detail", "Shared request protection service is unavailable")
        return JSONResponse(
            status_code=status_code,
            content={"detail": detail, "request_id": request_id},
            headers={"X-Request-ID": request_id, **(getattr(exc, "headers", None) or {})},
        )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    try:
        await store_request_metadata(request_id, request, response.status_code)
    except Exception:
        # Initial write succeeded, so the ID exists; status enrichment is best-effort.
        pass
    return response


app.include_router(router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok", "service": "agrostock-api"}
