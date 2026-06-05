from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, *, token_version: int | None = None):
    """Mint a JWT.

    Always include `iat` (issued-at) and, when `token_version` is given,
    embed it as `tv` so the auth dependency can revoke older tokens by
    bumping `users.token_version` (audit CRIT-8).
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    to_encode["exp"] = expire
    to_encode["iat"] = datetime.utcnow()
    if token_version is not None:
        to_encode["tv"] = int(token_version)

    return jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.algorithm,
    )
