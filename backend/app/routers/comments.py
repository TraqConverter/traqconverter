"""Deprecated. Replaced by app.routers.segment_comments which is auth-scoped.

The previous implementation in this file accepted a `user_id` from the
request body and had no authentication, allowing any anonymous caller to
post comments as any user. The audit flagged it as CRIT-4. The router
was never registered in main.py, but the file remained as a footgun.

We now expose a stub router that intentionally raises 410 Gone on every
call so any leftover client code (or future accidental import) fails
loudly instead of silently exposing the data.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/comments", tags=["comments-deprecated"])


@router.api_route("/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE"])
def gone(rest: str):
    raise HTTPException(
        status_code=410,
        detail="This endpoint is removed. Use /segments/{id}/comments instead.",
    )
