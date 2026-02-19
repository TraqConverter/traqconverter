from fastapi import FastAPI, Depends
from app.config import settings
from app.database import engine, Base
from app.models import user
from app.models import team
from app.models import credit
from app.models import job
from app.models.user import User
from app.dependencies import get_current_user

from app.routers import auth
from app.routers import jobs
from app.routers import subscription  # make sure this exists


# ✅ CREATE APP FIRST
app = FastAPI(title=settings.app_name)


# ✅ INCLUDE ROUTERS AFTER APP EXISTS
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(subscription.router)


@app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "TraqConverter API running"}


@app.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
    }
