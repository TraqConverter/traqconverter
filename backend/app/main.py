import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pathlib import Path

from app.core.logging_config import configure_logging

# ----------------------------------------------------
# Load environment variables
# ----------------------------------------------------
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# ----------------------------------------------------
# Configure logging (must run BEFORE anything else)
# ----------------------------------------------------
configure_logging()

logger = logging.getLogger(__name__)
logger.info("Starting TraqConverter API")

# ----------------------------------------------------
# Create FastAPI app
# ----------------------------------------------------
app = FastAPI()

# ----------------------------------------------------
# STEP 5: Enable CORS (for frontend access)
# ----------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict to frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------
# Global Exception Logging
# ----------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# ----------------------------------------------------
# Health Check Endpoint
# ----------------------------------------------------
@app.get("/health")
def health_check():
    return {"status": "ok"}

# ----------------------------------------------------
# Import routers AFTER app creation
# ----------------------------------------------------
from app.routers import stripe
from app.routers import subscription
from app.routers import auth
from app.routers import project
from app.routers import settings
from app.routers import billing
from app.routers import segments
from app.routers import comments   

# ----------------------------------------------------
# Register routers
# ----------------------------------------------------
app.include_router(settings.router)
app.include_router(stripe.router)
app.include_router(subscription.router)
app.include_router(auth.router)
app.include_router(project.router)
app.include_router(billing.router)
app.include_router(segments.router)
app.include_router(comments.router)

logger.info("All routers registered successfully")