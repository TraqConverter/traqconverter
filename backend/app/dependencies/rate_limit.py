"""In-memory sliding-window rate limits (single process; swap the dict for Redis if the API scales out)."""
from __future__ import annotations

import os
import time
from collections import deque
from typing import Deque, Dict, Tuple

from fastapi import Depends, HTTPException, Request, status

_buckets: Dict[Tuple[str, str], Deque[float]] = {}

# Number of trusted reverse proxies in front of the API (Railway/Render add one).
PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))


def client_ip(request: Request) -> str:
    # Only the entries appended by our own proxies can be trusted; anything left of them is client-supplied.
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if PROXY_HOPS > 0 and len(forwarded) >= PROXY_HOPS:
        return forwarded[-PROXY_HOPS]
    return request.client.host if request.client else "unknown"


def _hit(key: Tuple[str, str], max_requests: int, per_seconds: int) -> None:
    now = time.monotonic()
    bucket = _buckets.setdefault(key, deque())
    while bucket and bucket[0] < now - per_seconds:
        bucket.popleft()
    if len(bucket) >= max_requests:
        retry_after = max(1, int(bucket[0] + per_seconds - now))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests — please slow down and try again.",
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)


def rate_limit(scope: str, max_requests: int, per_seconds: int):
    """Per-client-IP limit."""
    def _dep(request: Request):
        _hit((client_ip(request), scope), max_requests, per_seconds)
        return True
    return _dep


def user_rate_limit(scope: str, max_requests: int, per_seconds: int):
    """Per-authenticated-user limit, for endpoints that spend AI budget."""
    from app.dependencies import get_current_user
    from app.models.user import User

    def _dep(current_user: User = Depends(get_current_user)):
        _hit((f"user:{current_user.id}", scope), max_requests, per_seconds)
        return True
    return _dep
