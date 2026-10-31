"""Distributed fixed-window rate limiting backed by Upstash Redis and Lua."""
import hashlib
import os
import re
import asyncio
from fastapi import HTTPException, Request
from .upstash import get_redis

WINDOW_SECONDS = max(1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")))
GENERAL_LIMIT = max(1, int(os.getenv("RATE_LIMIT_REQUESTS", "120")))
AUTH_LIMIT = max(1, int(os.getenv("AUTH_RATE_LIMIT_REQUESTS", "10")))

INCREMENT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return current
"""


def _client_key(request: Request) -> str:
    client = request.client.host if request.client else "unknown"
    # Do not persist raw IP addresses in Redis keys.
    return hashlib.sha256(client.encode("utf-8")).hexdigest()


def _route_key(request: Request) -> str:
    path = re.sub(r"/\d+(?=/|$)", "/{id}", request.url.path)
    if path in {"/api/auth/login", "/api/auth/signup"}:
        path = "/api/auth/*"
    return f"agrostock:rate:{_client_key(request)}:{request.method}:{path}"


async def enforce_rate_limit(request: Request) -> None:
    try:
        redis = get_redis()
        limit = AUTH_LIMIT if request.url.path in {"/api/auth/login", "/api/auth/signup"} else GENERAL_LIMIT
        count = await asyncio.to_thread(
            redis.eval,
            INCREMENT_SCRIPT,
            [_route_key(request)],
            [str(WINDOW_SECONDS)],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Rate-limit service is not configured") from exc
    except Exception as exc:
        # Fail closed: never silently switch to an in-memory limiter.
        raise HTTPException(status_code=503, detail="Rate-limit service is temporarily unavailable") from exc

    if int(count) > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again shortly.",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )
