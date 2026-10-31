"""Request ID middleware helpers; request metadata is retained in Upstash for tracing."""
import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from fastapi import Request
from .upstash import get_redis

REQUEST_ID_TTL_SECONDS = max(60, int(os.getenv("REQUEST_ID_TTL_SECONDS", "86400")))
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


def resolve_request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "").strip()
    return supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid.uuid4())


async def store_request_metadata(request_id: str, request: Request, status_code: int | None = None) -> None:
    payload = {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if status_code is not None:
        payload["status_code"] = status_code
    redis = get_redis()
    await asyncio.to_thread(
        redis.set,
        f"agrostock:request:{request_id}",
        json.dumps(payload, separators=(",", ":")),
        ex=REQUEST_ID_TTL_SECONDS,
    )
