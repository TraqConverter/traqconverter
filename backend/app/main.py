import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
# Import routers AFTER app creation
# ----------------------------------------------------
from app.routers import stripe
from app.routers import subscription
from app.routers import auth
from app.routers import project
from app.routers import settings

# ----------------------------------------------------
# Register routers
# ----------------------------------------------------
app.include_router(settings.router)
app.include_router(stripe.router)
app.include_router(subscription.router)
app.include_router(auth.router)
app.include_router(project.router)

logger.info("All routers registered successfully")