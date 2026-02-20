from fastapi import FastAPI
from dotenv import load_dotenv
from pathlib import Path

# Load .env from backend root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

app = FastAPI()

# Import routers AFTER app creation
from app.routers import stripe
from app.routers import subscription
from app.routers import auth   # ✅ ADD THIS

# Register routers
app.include_router(stripe.router)
app.include_router(subscription.router)
app.include_router(auth.router)  # ✅ ADD THIS