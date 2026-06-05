"""In-memory IP rate limiter for /auth endpoints.

Audit CRIT-7 fix: prior to this, /auth/login and /auth/register accepted
unlimited requests, enabling password brute-force and account
enumeration. This dependency caps requests per IP per route in a sliding
window.

This is a single-process limiter — fine for one uvicorn worker. For a
multi-instance deployment swap the in-memory dict for Redis (the
interface is identical: increment-and-check). The api boundary stays
the same so callers don't change.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status

# (ip, scope) → deque of timestamps
_buckets: Dict[Tuple[str, str], Deque[float]] = {}


def rate_limit(scope: str, max_requests: int, per_seconds: int):
    """Return a FastAPI dependency that throttles `scope` to
    `max_requests` per `per_seconds` per client IP.
    """

    def _dep(request: Request):
        ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        key = (ip, scope)

        now = time.monotonic()
        window_start = now - per_seconds
        bucket = _buckets.setdefault(key, deque())

        # Drop timestamps that fell out of the window.
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= max_requests:
            retry_after = max(1, int(bucket[0] + per_seconds - now))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests — please slow down and try again.",
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
        return True

    return _dep
