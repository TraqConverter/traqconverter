from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.user import User

security = HTTPBearer(auto_error=False)


def _validate_token(token: str, db: Session) -> User:
    """Decode + check a JWT, return the matching User. Raises 401
    on any failure. Centralises the token-version revoke check so
    bearer + query-string paths share one truth."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    expected_tv = int(getattr(user, "token_version", 0) or 0)
    token_tv = payload.get("tv")
    actual_tv = int(token_tv) if token_tv is not None else 0
    if actual_tv != expected_tv:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired — please sign in again",
        )
    return user


def get_current_user_or_query(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    access_token: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> User:
    """Auth that accepts EITHER an Authorization: Bearer header OR a
    ?access_token=... query parameter. Used by preview/streaming
    endpoints that are loaded into <iframe> tags — iframes can't
    send custom headers, so the JWT has to ride along in the URL.
    The token is still validated the same way.
    """
    if credentials and credentials.credentials:
        return _validate_token(credentials.credentials, db)
    if access_token:
        return _validate_token(access_token, db)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return _validate_token(credentials.credentials, db)
