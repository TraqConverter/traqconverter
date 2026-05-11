from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings


# Audit medium fix: the engine used to default to SQLAlchemy's pool of 5
# connections with no recycle, no pre-ping. Under moderate load that
# exhausted the pool, and stale connections after an RDS failover
# returned 500s.
#
# - pool_pre_ping=True drops dead connections quietly before they're
#   handed to a request.
# - pool_recycle=1800 (30 min) closes a connection that's been idle for
#   too long, so we don't try to use one a load balancer has hung up.
# - pool_size=10 + max_overflow=20 gives us 30 connections per app
#   instance, which scales well past the previous 5.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
