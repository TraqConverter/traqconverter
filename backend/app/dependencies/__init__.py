from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.user import User

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    token = credentials.credentials

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
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Audit CRIT-8: enforce token_version. The JWT was signed with the
    # value of users.token_version at issue time. Bumping that column
    # (e.g. on password change) invalidates every older token instantly.
    expected_tv = int(getattr(user, "token_version", 0) or 0)
    token_tv = payload.get("tv")
    # Tokens issued before this change won't have `tv`; treat them as 0
    # so existing sessions don't all get kicked out at rollout.
    actual_tv = int(token_tv) if token_tv is not None else 0
    if actual_tv != expected_tv:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired — please sign in again",
        )

    return user
