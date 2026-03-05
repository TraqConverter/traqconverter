from sqlalchemy.orm import sessionmaker
from app.database import engine

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()