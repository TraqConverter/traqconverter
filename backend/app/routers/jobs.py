"""Deprecated. The job-creation flow is `/projects/upload`.

This file used to declare `@router.post(...)` without ever defining
`router`, so it threw a NameError on first import (audit HIGH-4). It was
never registered in main.py either. Replaced with an explicit stub so any
accidental import or registration fails loudly instead of silently."""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/jobs", tags=["jobs-deprecated"])


@router.api_route("/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE"])
def gone(rest: str):
    raise HTTPException(
        status_code=410,
        detail="This endpoint is removed. Use /projects/upload instead.",
    )
