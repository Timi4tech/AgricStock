"""Shared Upstash Redis client. No process-local rate-limit or idempotency storage."""
import os
from functools import lru_cache
from upstash_redis import Redis


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if not url or not token:
        raise RuntimeError(
            "Upstash Redis is required. Set UPSTASH_REDIS_REST_URL and "
            "UPSTASH_REDIS_REST_TOKEN in backend/.env."
        )
    return Redis(url=url, token=token)
