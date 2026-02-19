from fastapi import FastAPI
from app.config import settings
from app.database import engine, Base
from app.models import user
from app.models import team
from app.models import credit
from app.models import job
from app.routers import auth

app = FastAPI(title=settings.app_name)

from app.models import user
from app.models import team
from app.models import credit
from app.models import job

from app.routers import auth

app = FastAPI(title=settings.app_name)

app.include_router(auth.router)

@app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "TraqConverter API running"}
